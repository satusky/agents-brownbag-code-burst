"""NIH watch → Slack: route new NIH opportunities to RENCI's research groups.

The weekly job someone does by hand: read what NIH posted, decide which research
group (if any) should see each opportunity, and mention that group in the
funding channel.

* fetch (code): what NIH posted on Grants.gov in the last few weeks.
* screen (code): fixed rules drop what RENCI would not apply for: training and
  career awards, clinical trials required, limited competition, deadlines too
  close, and anything already posted. The rules are constants you can change.
* route (one worker per remaining opportunity, via Send): code reads the full
  record, including the program description from the full NOFO (Grants.gov's
  own synopsis is often one paragraph shared by a whole consortium), and the
  model makes one routing decision: a group and how well it fits, or none.
  Each call sees one opportunity and the group profiles, never the whole list,
  and the workers run in parallel.
* compose (code): all in one channel, a summary that counts the decisions made
  by code and by the model, then for each group with a fit, its mention above
  one table of its fits, strong first.
* approve (a person, ``interrupt()``), then post (code). A pass someone asked
  for in Slack (``requested_by``, see slack_bot.py) skips the pause:
  the request is the approval.

Guide: https://docs.langchain.com/oss/python/langgraph/workflows-agents#routing
Run:   uv run funding-watch run      (SLACK_MODE=practice, the default: nothing is sent)
Slack: README.md
"""

import json
import operator
import re
from collections import Counter
from datetime import timedelta
from typing import Annotated, Literal, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from pydantic import BaseModel, Field

from funding_watch.approval import request_approval
from funding_watch.checkpoint import make_checkpointer
from funding_watch.config import get_settings
from funding_watch.funding import load_groups
from funding_watch.funding.dates import (
    next_deadline,
    opportunity_status,
    today,
)
from funding_watch.funding.grantsgov import parse_date, record_from_hit
from funding_watch.funding.sources import get_source
from funding_watch.funding.tools import record_row
from funding_watch.slack import (
    get_slack,
    load_teams,
    mention,
    notifies,
    posted_ids,
    record_posted,
)
from funding_watch.models import get_model

# ----------------------------------------------------------------- prompts
ROUTE = (
    "Decide which of RENCI's research groups, if any, should see this new NIH funding opportunity, and how well "
    "it fits. RENCI (Renaissance Computing Institute, UNC-Chapel Hill) is a data science and computing institute: "
    "it leads or partners on data resources, data coordinating centers, knowledge graphs, data management, research "
    "software, cyberinfrastructure and AI or analytics methods. Most NIH opportunities are not a fit. "
    "fit is strong only when this award funds the applicant to build or run a data, computing or informatics role "
    "as a main deliverable: a data coordinating or data research center, a data resource or repository, an "
    "informatics or data science core, software or cyberinfrastructure. fit is possible when such a role is an "
    "optional or minor part of a research project, such as a study that may use AI or computational modeling. "
    "fit is none otherwise, including laboratory or clinical research, training and outreach. None of these is a "
    "role: the Data Management and Sharing Plan every NIH application includes, data sharing required of all "
    "awardees, or a role held by a companion award (clinical centers whose consortium funds a separate data "
    "center). NIH often gives every opportunity in a consortium the same short synopsis, so the title may be the "
    "only place the role is named; the title counts. For a strong or possible fit, copy the phrase that names the "
    "role into evidence, exactly as written. Give the reason in one sentence of at most 25 words; for a fit, say "
    "what the award would fund the group to do."
)

# Rules you can read and change: every code decision below follows from them.
AGENCY = "NIH"           # Grants.gov agency filter (code HHS-NIH11)
LOOKBACK_DAYS = 7        # window when the request names none ("last 4 weeks", "10 days")
MAX_DAYS = 56            # the longest posted-date window Grants.gov offers
MAX_RESULTS = 100        # Grants.gov rows read per run
MIN_DAYS_LEFT = 21       # fewer days to the next deadline: too soon to write a proposal
MAX_ROUTED = 30          # routing workers per run; any beyond are listed for a person
POST_FIT = "strong"      # "Strong" in the Fit column; any other fit the model names is "Possible"
BOILERPLATE = re.compile(  # not a role: every NIH application or award has one
    r"data management (?:and|&) sharing plan|\bDMS plan|resource sharing plan|data sharing plan", re.IGNORECASE)
MAX_TEXT = 8000          # announcement characters the model reads (NOFO purpose + program description)
TABLE_CHARS = 9000       # characters in one message's table; Slack allows 10,000 and one table per message
TRAINING_PREFIXES = ("F", "K", "T")              # NIH activity codes: fellowships, career awards, training
INDIVIDUAL_CODES = {"R25", "R36", "R50", "D43", "D71"}  # education, dissertation, research specialist, training
TITLE_RULES = (  # (pattern in the title, the rule that drops it)
    (r"Clinical Trial Required", "clinical trial required"),
    (r"^\s*(Limited Competition|Single Source)", "limited competition"),
)

GROUPS = {g.id: g for g in load_groups("renci")}
Team = Literal[(*GROUPS, "none")]
ACTIVITY = re.compile(r"\(([A-Z]{1,2}\d{1,2}[A-Z]?)(?:/([A-Z]{1,2}\d{1,2}[A-Z]?))?\b")  # "(R01 Clinical…", "(UH2/UH3 …", "(U2C)"

class Route(BaseModel):
    team: Team = Field(description="id of the research group that should see this opportunity, or none")
    fit: Literal["strong", "possible", "none"] = Field(
        description="strong: the award funds the role as a main deliverable; possible: an optional or minor part")
    evidence: str = Field(default="", description="For a group: the phrase naming the data, computing or "
                          "informatics role, copied exactly from the title or announcement. Empty for none.")
    reason: str = Field(description="One short sentence from the opportunity text: why this group, or why none")


route_llm = get_model().with_structured_output(Route)


class State(TypedDict, total=False):
    request: str
    channel: str               # where to post; default: the channel in teams.json
    requested_by: str          # Slack user who asked for this pass in Slack: no approval pause
    window: int                # days back, read from the request by code
    since: str
    hits: list[dict]           # what NIH posted in the window
    candidates: list[dict]     # what the rules kept: one routing worker each
    dropped: Annotated[list[dict], operator.add]  # what the rules dropped, with the rule
    routed: Annotated[list[dict], operator.add]   # one per worker: a group and its fit, or the rule that stopped it
    undecided: list[dict]      # over MAX_ROUTED: a person looks
    ledger: Annotated[list[dict], operator.add]   # {step, by, decisions, note}
    outbox: list[dict]         # Slack messages composed by code: channel, text, blocks
    approved: bool
    feedback: list[str]
    sent: list[dict]
    result: str


def entry(step: str, by: str, decisions: int, note: str) -> list[dict]:
    return [{"step": step, "by": by, "decisions": decisions, "note": note}]


def brief(row: dict) -> dict:
    return {k: row.get(k) for k in ("id", "number", "title", "url")}


def listing(rec: dict) -> dict:
    """What a Slack table row shows, kept from the full record."""
    return {k: rec.get(k) for k in ("id", "number", "title", "url", "posted", "forecast", "status", "award_max",
                                    "deadlines", "next_deadline")}


# ----------------------------------------------------------------- fetch and screen (code)
def window_days(request: str) -> int:
    """"last 4 weeks" → 28, "past 10 days" → 10; nothing stated → LOOKBACK_DAYS."""
    m = re.search(r"(\d+)\s*(day|week|month)", request or "", re.IGNORECASE)
    if not m:
        return LOOKBACK_DAYS
    days = int(m.group(1)) * {"day": 1, "week": 7, "month": 30}[m.group(2).lower()]
    return max(1, min(days, MAX_DAYS))


def nih_hits(days: int) -> list[dict]:
    """Raw Grants.gov rows for what NIH posted (or forecast) in about the last ``days`` days."""
    return get_source("live").grants.search(agencies=AGENCY, rows=MAX_RESULTS, posted_within=days)


def hit_row(hit: dict) -> dict:
    rec = record_from_hit(hit, "nih")
    posted = parse_date(hit.get("openDate"))
    return {**brief(rec.model_dump()), "agency": rec.agency, "posted": posted.isoformat() if posted else None,
            "forecast": hit.get("oppStatus") == "forecasted",
            "status": opportunity_status(rec), "next_deadline": next_deadline(rec)}


def activity_codes(title: str) -> list[str]:
    return [code for pair in ACTIVITY.findall(title) for code in pair if code]


def date_rule(status: str, deadline: dict | None) -> tuple[str, str] | None:
    if status == "closed":
        return "closed", "closed"
    if deadline and deadline["days_left"] < MIN_DAYS_LEFT:
        return "deadline too soon", f"{deadline['kind']} in {deadline['days_left']} days (minimum {MIN_DAYS_LEFT})"
    return None


def screen_rule(row: dict, posted: dict) -> tuple[str, str] | None:
    """(rule, detail) when code drops the opportunity; None keeps it for the model."""
    if row["id"] in posted:
        before = posted[row["id"]]
        return "already posted", f"posted for {before.get('team', '?')} on {before['posted'][:10]}"
    codes = activity_codes(row["title"])
    if codes and all(c.startswith(TRAINING_PREFIXES) or c in INDIVIDUAL_CODES for c in codes):
        return "training or career award", "/".join(codes)
    for pattern, rule in TITLE_RULES:
        if re.search(pattern, row["title"], re.IGNORECASE):
            return rule, rule
    return date_rule(row["status"], row.get("next_deadline"))


def fetch(state: State) -> dict:
    days = window_days(state.get("request", ""))
    since = (today() - timedelta(days=days)).isoformat()
    rows = [hit_row(h) for h in nih_hits(days)]
    rows = [r for r in rows if not r["posted"] or r["posted"] >= since]  # Grants.gov rounds up to whole weeks
    rows.sort(key=lambda r: r["posted"] or "", reverse=True)
    return {"window": days, "since": since, "hits": rows,
            "ledger": entry("fetch", "code", 1, f"NIH on Grants.gov, posted since {since}: {len(rows)}")}


def screen(state: State) -> dict:
    posted, kept, dropped = posted_ids(), [], []
    for row in state["hits"]:
        rule = screen_rule(row, posted)
        if rule:
            dropped.append({**brief(row), "by": "code", "rule": rule[0], "why": rule[1]})
        else:
            kept.append(row)
    counts = ", ".join(f"{n} {rule}" for rule, n in Counter(d["rule"] for d in dropped).most_common())
    note = f"kept {len(kept)}; dropped {len(dropped)}" + (f" ({counts})" if counts else "")
    return {"candidates": kept[:MAX_ROUTED], "undecided": kept[MAX_ROUTED:], "dropped": dropped,
            "ledger": entry("screen", "code", len(state["hits"]), note)}


def assign(state: State) -> list[Send] | str:
    """Code sends one routing worker per kept opportunity; with none, straight to compose."""
    if not state["candidates"]:
        return "compose"
    return [Send("route", {"opportunity": row}) for row in state["candidates"]]


# ----------------------------------------------------------------- route worker (subgraph)
class WorkerState(TypedDict, total=False):
    opportunity: dict  # the search row, from Send
    record: dict       # the full record, read by code
    routed: list[dict]


class WorkerOutput(TypedDict):
    routed: list[dict]  # the only key that flows back to the parent


def read(state: WorkerState) -> dict:
    """Code reads the full record. A forecast's estimated date can make it too soon after all."""
    row = state["opportunity"]
    try:
        rec = get_source("live").get(row["id"])
    except Exception:  # unreadable: the model judges the title
        rec = None
    if rec is None:
        return {"record": {**row, "announcement": "", "eligibility": []}}
    full = record_row(rec)
    record = {**row, **full, "announcement": full["announcement"][:MAX_TEXT], "next_deadline": next_deadline(rec)}
    rule = date_rule(record["status"], record["next_deadline"])
    if rule:
        return {"record": record, "routed": [{**brief(record), "team": None, "by": "code",
                                              "rule": rule[0], "why": rule[1]}]}
    return {"record": record}


def after_read(state: WorkerState) -> str:
    return END if state.get("routed") else "route"


def opportunity_text(rec: dict) -> str:
    return json.dumps({k: rec.get(k) for k in ("number", "title", "agency", "eligibility", "announcement")}, indent=1)


def route(state: WorkerState) -> dict:
    groups = [g.model_dump(include={"id", "name", "focus", "expertise", "projects"}) for g in GROUPS.values()]
    choice = route_llm.invoke([
        ("system", ROUTE),
        ("user", f"OPPORTUNITY:\n{opportunity_text(state['record'])}\n\nGROUPS:\n{json.dumps(groups, indent=1)}"),
    ])
    rec = state["record"]

    def stop(by: str, rule: str, why: str) -> dict:  # not a strong fit: compose decides where the rule shows
        return {"routed": [{**listing(rec), "team": None, "suggested": choice.team, "evidence": choice.evidence,
                            "by": by, "rule": rule, "why": why}]}

    if choice.team == "none" or choice.fit == "none":
        return stop("model", "not a fit", choice.reason)
    if BOILERPLATE.search(choice.evidence):  # code checks the model: a plan every application has is not a role
        return stop("code", "boilerplate evidence", f"“{choice.evidence}” is in every NIH application")
    if not quoted(choice.evidence, f"{rec['title']} {rec.get('announcement', '')}"):  # and the quote must be real
        return stop("code", "needs a person", "the model's evidence is not in the record")
    if choice.fit != POST_FIT:
        return stop("model", "possible fit", choice.reason)
    return {"routed": [{**listing(rec), "team": choice.team, "fit": choice.fit, "evidence": choice.evidence,
                        "by": "model", "why": choice.reason}]}


def words(text: str) -> str:
    return " ".join(re.findall(r"\w+", text.lower()))


def quoted(evidence: str, text: str) -> bool:
    """True when the evidence appears in the text, ignoring case, punctuation and spacing."""
    phrase = words(evidence or "")
    return len(phrase) >= 8 and f" {phrase} " in f" {words(text)} "


worker_builder = StateGraph(WorkerState, output_schema=WorkerOutput)
worker_builder.add_node("read", read)
worker_builder.add_node("route", route)
worker_builder.add_edge(START, "read")
worker_builder.add_conditional_edges("read", after_read, ["route", END])
worker_builder.add_edge("route", END)
worker_graph = worker_builder.compile()


# ----------------------------------------------------------------- Slack formatting (code)
def esc(text) -> str:
    """Slack treats &, < and > as control characters."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def mrkdwn(text: str) -> dict:
    return {"type": "mrkdwn", "text": text[:2900]}


def deadline_text(r: dict) -> str:
    d = r.get("next_deadline")
    if d:
        return f"{d['date']} ({d['days_left']} days, {d['kind']})"
    return "rolling" if r.get("status") == "rolling" else "not yet announced" if r.get("forecast") else "not stated"


def deadlines_text(r: dict) -> str:
    """Every deadline still ahead, soonest first."""
    ahead = [d for d in r.get("deadlines") or [] if d["days_left"] >= 0]
    if not ahead:
        return deadline_text(r)
    return "; ".join(f"{d['date']} {d['kind']} ({d['days_left']} days)" for d in ahead)


def label(r: dict) -> str:
    return r.get("number") or r["id"]


def bullet(r: dict, extra: str = "") -> str:
    return f"• <{r['url']}|{esc(label(r))}> {esc(r['title'])}{extra}"


def capped(lines: list[str], limit: int = 8, chars: int = 2600) -> str:
    """At most ``limit`` whole lines within Slack's section size, then a count of the rest."""
    kept = []
    for line in lines[:limit]:
        if sum(len(k) + 1 for k in kept) + len(line) > chars:
            break
        kept.append(line)
    rest = len(lines) - len(kept)
    return "\n".join(kept + ([f"…and {rest} more"] if rest else []))


# Slack tables: one per message, shown at the bottom of it.
COLUMNS = ("ID", "Fit", "Title", "Why it fits", "Amount", "Posted", "Deadlines")
COLUMN_SETTINGS = [  # one object per column: Slack rejects null here, though its docs allow it
    {"align": "left"}, {"align": "left"}, {"is_wrapped": True}, {"is_wrapped": True}, {"align": "right"},
    {"align": "left"}, {"is_wrapped": True}]
FITS = ("strong", "possible")  # table order


def row_texts(r: dict) -> list[str]:
    """One opportunity as table cells, in COLUMNS order."""
    return [label(r), (r.get("fit") or "").capitalize(), clip(r["title"], 200),
            clip(r.get("why") or "", 240) or "not stated",
            f"${r['award_max']:,}" if r.get("award_max") else "not stated",
            (r.get("posted") or "unknown") + (" (forecast)" if r.get("forecast") else ""),
            deadlines_text(r)]


def cell(text: str, url: str | None = None, bold: bool = False) -> dict:
    """A rich_text table cell: plain text, a link, or bold."""
    element = {"type": "link", "url": url, "text": text} if url else {"type": "text", "text": text}
    if bold:
        element["style"] = {"bold": True}
    return {"type": "rich_text", "elements": [{"type": "rich_text_section", "elements": [element]}]}


def table_block(rows: list[dict]) -> dict:
    body = [[cell(text, url=r.get("url") if i == 0 else None) for i, text in enumerate(row_texts(r))] for r in rows]
    return {"type": "table", "column_settings": COLUMN_SETTINGS, "rows": [[cell(c, bold=True) for c in COLUMNS], *body]}


def table_chunks(rows: list[dict], chars: int = TABLE_CHARS, limit: int = 99) -> list[list[dict]]:
    """Rows split so that each message's table stays within Slack's limits (characters and 100 rows)."""
    chunks, size = [[]], 0
    for r in rows:
        n = sum(map(len, row_texts(r)))
        if chunks[-1] and (size + n > chars or len(chunks[-1]) >= limit):
            chunks.append([])
            size = 0
        chunks[-1].append(r)
        size += n
    return chunks


def fit_counts(rows: list[dict]) -> str:
    """"1 strong and 2 possible fits", "1 strong fit"."""
    counts = Counter(r["fit"] for r in rows)
    parts = [f"{counts[fit]} {fit}" for fit in FITS if counts[fit]]
    return " and ".join(parts) + (" fit" if len(rows) == 1 else " fits")


def team_messages(gid: str, rows: list[dict], who: str, channel: str) -> list[dict]:
    """A group's fits in one table, under its mention (the mention names the group).

    Slack allows one table per message, so a table too big for one message continues in the next.
    """
    out = []
    for i, chunk in enumerate(table_chunks(rows)):
        head = (who or f"*{esc(GROUPS[gid].name)}*") if i == 0 else f"*{esc(GROUPS[gid].name)}* (continued)"
        out.append({"channel": channel, "group": gid, "ids": [r["id"] for r in chunk],
                    "fits": {r["id"]: r["fit"] for r in chunk},
                    "text": f"{who or esc(GROUPS[gid].name)} {fit_counts(rows)}: " + ", ".join(label(r) for r in chunk),
                    "blocks": [{"type": "section", "text": mrkdwn(f"{head} · {fit_counts(rows)}")},
                               table_block(chunk)]})
    return out


def digest_blocks(state: State, strong: list[dict], possible: list[dict], needs_person: list[dict],
                  code_drops: list[dict], judged: int, groups: int, ledger: list[dict]) -> list[dict]:
    """The run in a few lines: counts, anything a person must look at, and who decided what."""
    by_code = sum(e["decisions"] for e in ledger if e["by"] == "code")
    by_model = sum(e["decisions"] for e in ledger if e["by"] == "model")
    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": f"NIH funding watch · {state['since']} to {today()}"}},
        {"type": "section", "text": mrkdwn(
            f"*{len(state['hits'])}* posted by NIH · *{len(code_drops)}* dropped by rules · "
            f"*{judged}* judged by the model → *{len(strong)}* strong and *{len(possible)}* possible fits "
            f"for *{groups}* research {'group' if groups == 1 else 'groups'}")},
    ]
    if needs_person:
        blocks.append({"type": "section", "text": mrkdwn(
            "*Needs a person* (the model's evidence was not in the record)\n"
            + capped([bullet(r, f" · model suggested {GROUPS[r['suggested']].name}") for r in needs_person]))})
    if state.get("undecided"):
        blocks.append({"type": "section", "text": mrkdwn(
            f"*Not reviewed* (over the {MAX_ROUTED}-per-run cap)\n" + capped([bullet(r) for r in state["undecided"]]))})
    blocks += [
        {"type": "context", "elements": [mrkdwn(
            "*Strong*: the award funds a data, computing or informatics role as a main deliverable. "
            "*Possible*: such a role is optional or a minor part.")]},
        {"type": "context", "elements": [mrkdwn(
            f"{by_code} decisions by code · {by_model} by the model · "
            + (f"requested by <@{state['requested_by']}> in Slack" if state.get("requested_by")
               else "approved by a person before posting"))]},
    ]
    return blocks


def to_markdown(text: str) -> str:
    """Slack mrkdwn → Markdown, for the preview a person approves."""
    text = re.sub(r"<(https?://[^|>]+)\|([^>]+)>", r"[\2](\1)", text)
    text = re.sub(r"<#([A-Z0-9]+)>", r"#\1", text)
    text = re.sub(r"<(?:!subteam\^|@)([A-Z0-9]+)>", r"@\1", text)
    text = re.sub(r"(?<![*\w])\*([^*\n]+)\*(?![*\w])", r"**\1**", text)
    return text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def cell_markdown(c: dict) -> str:
    parts = [f"[{e['text']}]({e['url']})" if e["type"] == "link" else e.get("text", "")
             for section in c.get("elements", []) for e in section.get("elements", [])]
    text = "".join(parts) if c["type"] == "rich_text" else str(c.get("text", ""))
    return text.replace("|", "\\|").replace("\n", " ")


def table_markdown(block: dict) -> str:
    head, *body = [[cell_markdown(c) for c in row] for row in block["rows"]]
    return "\n".join(["| " + " | ".join(head) + " |", "|" + " --- |" * len(head)]
                     + ["| " + " | ".join(row) + " |" for row in body])


def preview(outbox: list[dict]) -> str:
    """Every message as it will appear, rendered from its blocks."""
    if not outbox:
        return ""
    head = f"**{len(outbox)} messages → " + ", ".join(dict.fromkeys(m["channel"] for m in outbox)) + "**"
    parts = []
    for m in outbox:
        lines = []
        for b in m["blocks"]:
            if b["type"] == "header":
                lines.append(f"**{b['text']['text']}**")
            elif b["type"] == "section" and "fields" in b:
                lines.append(" · ".join(to_markdown(f["text"]).replace("\n", " ") for f in b["fields"]))
            elif b["type"] == "section":
                lines.append(to_markdown(b["text"]["text"]))
            elif b["type"] == "context":
                lines.append("_" + to_markdown(" ".join(e["text"] for e in b["elements"])) + "_")
            elif b["type"] == "table":
                lines.append(table_markdown(b))
        parts.append("\n\n".join(lines))
    return head + "\n\n" + "\n\n---\n\n".join(parts)


# ----------------------------------------------------------------- compose, approve, post
READ_RULES = ("closed", "deadline too soon")  # code, after reading the full record
RULES_AFTER_READ = ("not a fit", "possible fit", "boilerplate evidence", "needs a person")


def compose(state: State) -> dict:
    """Plain code: in one channel, the summary, then each group's mention and tables of its fits."""
    slack, results = load_teams(), state.get("routed", [])
    slack["channel"] = state.get("channel") or slack["channel"]
    strong = sorted((r for r in results if r.get("team")), key=deadline_text)
    by_rule = {rule: sorted((r for r in results if r.get("rule") == rule), key=deadline_text)
               for rule in RULES_AFTER_READ}
    possible = by_rule["possible fit"]
    late = [r for r in results if r.get("rule") in READ_RULES]  # dropped by code before any model call
    code_drops = state.get("dropped", []) + late + by_rule["boilerplate evidence"]
    judged = len(results) - len(late)
    chose = judged - len(by_rule["not a fit"])
    ledger = list(state.get("ledger", []))
    if late:
        ledger += entry("read", "code", len(late), f"{len(late)} dropped after reading the full record")
    ledger += entry("route", "model", judged, f"{judged} workers in parallel: {chose} chose a group, "
                                              f"{len(by_rule['not a fit'])} none")
    if chose:
        ledger += entry("check", "code", chose,
                        f"{len(strong)} {POST_FIT} with evidence; {len(possible)} possible; "
                        f"{len(by_rule['boilerplate evidence'])} boilerplate evidence; "
                        f"{len(by_rule['needs a person'])} evidence not in the record → a person")
    fits = {gid: [{**r, "fit": "strong"} for r in strong if r["team"] == gid]
                 + [{**r, "fit": "possible"} for r in possible if r.get("suggested") == gid] for gid in GROUPS}
    fits = {gid: rows for gid, rows in fits.items() if rows}  # strong first, each by deadline
    outbox = []
    if slack["digest"]:
        outbox.append({"channel": slack["channel"], "group": None, "ids": [], "fits": {},
                       "text": f"NIH funding watch: {len(strong)} strong and {len(possible)} possible fits",
                       "blocks": digest_blocks(state, strong, possible, by_rule["needs a person"], code_drops,
                                               judged, len(fits), ledger)})
    for gid, rows in fits.items():
        outbox += team_messages(gid, rows, mention(slack["teams"].get(gid)), slack["channel"])
    silent = [gid for gid in fits if not notifies(slack["teams"].get(gid))]
    note = f"{len(outbox)} messages to {slack['channel']} for {len(fits)} {'group' if len(fits) == 1 else 'groups'}" + (
        f"; no Slack ID to mention for {', '.join(silent)}" if silent else "")
    ledger_update = ledger[len(state.get("ledger", [])):] + entry("compose", "code", len(outbox), note)
    return {"outbox": outbox, "ledger": ledger_update, "result": preview(outbox) or "Nothing to post."}


def after_compose(state: State) -> str:
    return "approve" if state["outbox"] else END


def approve(state: State) -> dict:
    if state.get("requested_by"):  # someone asked for this pass in Slack: the request is the approval
        return {"approved": True, "feedback": []}
    mode = get_settings().slack_mode
    ask = f"Post these {len(state['outbox'])} messages to Slack?" + (
        " (practice mode: nothing is sent)" if mode != "live" else "")
    answer = request_approval({"preview": preview(state["outbox"])}, ask=ask)
    if answer.approved:
        return {"approved": True, "feedback": []}
    return {"approved": False, "feedback": answer.feedback,
            "result": "Not approved: nothing was posted.\n\n" + "\n".join(f"- {f}" for f in answer.feedback)}


def after_approve(state: State) -> str:
    return "post" if state["approved"] else END


def post(state: State) -> dict:
    slack, sent, posted = get_slack(), [], {}
    for m in state["outbox"]:
        result = slack.post(m["channel"], m["text"], m["blocks"])
        sent.append({**result, "group": m["group"]})
        if result["ok"] and slack.mode == "live":  # each opportunity in a posted table is not posted again
            posted.update({oid: {"team": m["group"], "fit": m["fits"][oid], "channel": m["channel"]}
                           for oid in m["ids"]})
    record_posted(posted)
    ok = sum(r["ok"] for r in sent)
    head = (f"Posted {ok} of {len(sent)} messages to Slack." if slack.mode == "live" else
            f"Practice mode: {ok} messages composed, none sent. Set SLACK_MODE=live to post them.")
    what = [GROUPS[r["group"]].name if r["group"] else "summary" for r in sent]
    lines = [head, ""] + [f"- {r['channel']} · {w}: {'ok' if r['ok'] else r['error']}" for r, w in zip(sent, what)]
    return {"sent": sent, "result": "\n".join(lines) + "\n\n---\n\n" + state["result"]}

builder = StateGraph(State)
builder.add_node("fetch", fetch)
builder.add_node("screen", screen)
builder.add_node("route", worker_graph)  # a compiled graph is a node; Send starts one per opportunity
builder.add_node("compose", compose)
builder.add_node("approve", approve)
builder.add_node("post", post)
builder.add_edge(START, "fetch")
builder.add_edge("fetch", "screen")
builder.add_conditional_edges("screen", assign, ["route", "compose"])
builder.add_edge("route", "compose")
builder.add_conditional_edges("compose", after_compose, ["approve", END])
builder.add_conditional_edges("approve", after_approve, ["post", END])
builder.add_edge("post", END)
graph = builder.compile(checkpointer=make_checkpointer())  # approve pauses, so it needs a checkpointer

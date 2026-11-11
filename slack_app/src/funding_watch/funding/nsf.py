"""NSF: solicitation pages and the Award Search API (no key required).

NSF lists every funding opportunity on Grants.gov, but Grants.gov keeps only
the final close date. The NSF solicitation page has the full schedule (letter
of intent, preliminary proposal, full proposal), so ``read_page`` parses it.

* Solicitation pages: https://www.nsf.gov/funding/opportunities/...
* Award Search API:   https://resources.research.gov/common/webapi/awardapisearch-v1.htm
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime

import httpx

from funding_watch.funding.grantsgov import html_to_text, money
from funding_watch.funding.schemas import Deadline

AWARDS_API = "https://api.nsf.gov/services/v1/awards.json"
AWARD_FIELDS = ("id,title,awardeeName,awardeeStateCode,fundsObligatedAmt,estimatedTotalAmt,startDate,expDate,"
                "fundProgramName,dirAbbr,divAbbr,transType,abstractText")

# Due-date headings on NSF solicitations, and the deadline kind each one means.
DUE_DATE_HEADINGS = {
    "Letter of Intent Due Date(s)": "letter of intent",
    "Preliminary Proposal Due Date(s)": "preliminary proposal",
    "Full Proposal Deadline(s)": "full proposal",
    "Full Proposal Target Date(s)": "full proposal target date",
    "Submission Window Date(s)": "submission window closes",
}
ANYTIME = "Proposals Accepted Anytime"
_HEADING = re.compile("|".join(re.escape(h) for h in [*DUE_DATE_HEADINGS, ANYTIME]), re.I)
_DATE = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},?\s+\d{4}"
_RANGE = re.compile(rf"({_DATE})\s*-\s*({_DATE})")


def _to_date(text: str) -> date:
    return datetime.strptime(" ".join(text.replace(",", " ").split()), "%B %d %Y").date()


def parse_due_dates(text: str) -> tuple[list[Deadline], bool]:
    """Deadlines under each due-date heading, plus whether proposals are accepted anytime."""
    found: list[Deadline] = []
    rolling = False
    marks = list(_HEADING.finditer(text))
    for i, m in enumerate(marks):
        heading = next(h for h in [*DUE_DATE_HEADINGS, ANYTIME] if h.lower() == m.group(0).lower())
        if heading == ANYTIME:
            rolling = True
            continue
        end = marks[i + 1].start() if i + 1 < len(marks) else m.end() + 600
        section = text[m.end():end]
        section = re.split(r"\n(?:TABLE OF CONTENTS|Important Information|Proposal Review Information)", section)[0]
        kind = DUE_DATE_HEADINGS[heading]
        if kind == "submission window closes":
            dates = [_to_date(b) for _, b in _RANGE.findall(section)]
        else:
            dates = [_to_date(d) for d in re.findall(_DATE, section)]
        found += [Deadline(kind=kind, date=d) for d in dates]
    unique = {(d.kind, d.date): d for d in found}
    return sorted(unique.values(), key=lambda d: d.date), rolling


def due_block(text: str) -> str:
    """The due-date headings and dates as NSF wrote them (including "Annually Thereafter" notes)."""
    marks = list(_HEADING.finditer(text))
    if not marks:
        return ""
    block = text[marks[0].start():marks[-1].end() + 400]
    block = re.split(r"\n(?:TABLE OF CONTENTS|Important Information|Proposal Review Information)", block)[0]
    return block.replace("(due by 5 p.m. submitting organization's local time):", "").strip()[:1200]


def _between(text: str, start: str, *ends: str, limit: int = 3000) -> str:
    i = text.find(start)
    if i < 0:
        return ""
    i += len(start)
    stops = [j for j in (text.find(e, i) for e in ends) if j >= 0]
    return text[i:min(stops, default=i + limit)][:limit].strip(" :\n")


@dataclass
class NSFPage:
    url: str
    title: str = ""
    text: str = ""
    deadlines: list[Deadline] = field(default_factory=list)
    rolling: bool = False
    award_max: int | None = None


def parse_page(markup: str, url: str) -> NSFPage:
    """Turn an NSF solicitation (or program) page into announcement text and deadlines."""
    title = html_to_text((re.search(r"<title>(.*?)</title>", markup, re.S | re.I) or [None, ""])[1])
    title = title.split(" | NSF")[0]
    text = html_to_text(markup)
    head = text.split("TABLE OF CONTENTS")[0]
    deadlines, rolling = parse_due_dates(head)

    if "Synopsis of Program" in text:  # a solicitation
        parts = {
            "Synopsis": _between(text, "Synopsis of Program", "Expanding Participation", "NSF Priorities",
                                 "Cognizant Program Officer", "Applicable Catalog"),
            "Award information": _between(text, "Anticipated Type of Award", "Proposal Preparation and Submission",
                                          limit=1200),
            "Letters of intent": _between(text, "Letters of Intent:", "Preliminary Proposal", limit=200),
            "Preliminary proposals": _between(text, "Preliminary Proposal Submission:", "Full Proposal", limit=300)
            or _between(text, "Preliminary Proposals:", "Full Proposal", limit=300),
            "Due dates": due_block(head),
            "Who may submit": _between(text, "Who May Submit Proposals", "Who May Serve as PI", limit=1800),
            "Who may serve as PI": _between(text, "Who May Serve as PI", "Limit on Number of Proposals", limit=600),
            "Limit on proposals": _between(text, "Limit on Number of Proposals per Organization",
                                           "Limit on Number of Proposals per PI", limit=300),
        }
        info = parts["Award information"]
        total = re.search(r"Anticipated Funding Amount:?\s*\$([\d,]+)", info)
        caps = {money(c) for c in re.findall(r"(?:maximum|up to) \$([\d,]+)", info)}
        caps.discard(money(total.group(1)) if total else None)  # the program total is not a per-award cap
        award_max = max(caps, default=None)  # with several tracks, the largest cap
    else:  # a program page: synopsis plus the due-date block as written
        parts = {
            "Synopsis": _between(text, "Synopsis", "Program contacts", "Upcoming due dates", "Program Contacts",
                                 limit=2500),
            "Due dates": _between(text, "Upcoming due dates", "Program contacts", "Program Contacts",
                                  "Additional information", limit=800),
        }
        rolling = rolling or "accepted anytime" in parts["Due dates"].lower()
        award_max = None
    body = "\n\n".join(f"{k}: {v}" for k, v in parts.items() if v)
    return NSFPage(url=url, title=title, text=body, deadlines=deadlines, rolling=rolling, award_max=award_max)


def award_query(query: str) -> str:
    """The awards API ORs bare words; AND them so results stay on topic."""
    words = [w for w in re.findall(r"[A-Za-z0-9-]+", query) if len(w) > 2 and w.lower() not in _STOP]
    return " AND ".join(words[:5]) or query


_STOP = set("and for the with from that this our are what which who how into about".split())


class NSFClient:
    def __init__(self, timeout: float = 30.0):
        self.http = httpx.Client(timeout=timeout, follow_redirects=True,
                                 headers={"User-Agent": "Mozilla/5.0 (funding-analyst workshop)"})

    def read_page(self, url: str) -> NSFPage | None:
        """None when the page is unavailable (NSF sometimes answers with a bot challenge)."""
        try:
            resp = self.http.get(url.replace("http://", "https://"))
        except httpx.HTTPError:
            return None
        if resp.status_code != 200 or "<html" not in resp.text[:2000].lower():
            return None
        return parse_page(resp.text, str(resp.url))

    def awards(self, query: str, limit: int = 5) -> list[dict]:
        """Recent NSF awards matching the query, newest first."""
        resp = self.http.get(AWARDS_API, params={"keyword": award_query(query), "rpp": limit,
                                                 "printFields": AWARD_FIELDS})
        resp.raise_for_status()
        return [award_row(a) for a in resp.json().get("response", {}).get("award", [])[:limit]]


def award_row(a: dict) -> dict:
    return {
        "award_id": a.get("id"),
        "title": a.get("title", ""),
        "institution": a.get("awardeeName", ""),
        "state": a.get("awardeeStateCode", ""),
        "program": a.get("fundProgramName", ""),
        "directorate": "/".join(x for x in (a.get("dirAbbr"), a.get("divAbbr")) if x),
        "amount": money(a.get("estimatedTotalAmt") or a.get("fundsObligatedAmt")),
        "start": a.get("startDate"),
        "end": a.get("expDate"),
        "abstract": (a.get("abstractText") or "")[:400],
        "url": f"https://www.nsf.gov/awardsearch/showAward?AWD_ID={a.get('id')}",
    }

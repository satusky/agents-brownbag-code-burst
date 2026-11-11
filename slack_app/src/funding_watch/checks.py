"""Setup check: settings, then the three endpoint compatibility checks.

1. A normal model invocation.
2. A structured-output invocation (including a date field).
3. A complete model → tool → model round trip.
"""

from __future__ import annotations

import time
from datetime import date

from pydantic import BaseModel


def _step(label: str, fn) -> bool:
    t0 = time.monotonic()
    try:
        detail = fn()
        print(f"  ✓ {label} ({time.monotonic() - t0:.1f}s){f': {detail}' if detail else ''}")
        return True
    except Exception as exc:
        print(f"  ✗ {label}: {type(exc).__name__}: {exc}")
        return False


def run_checks() -> bool:
    from funding_watch.config import get_settings

    s = get_settings()
    print("Settings")
    print(f"  endpoint host      {s.endpoint_host or '(missing)'}")
    print(f"  model              {s.model or '(missing)'}")
    print(f"  structured output  {s.structured_output_method}")
    print(f"  funding source     {s.funding_source}")
    print(f"  today              {s.today()}{' (pinned)' if s.demo_today.lower() != 'today' else ''}")
    if not s.configured:
        print(f"  ✗ missing: {', '.join(s.missing)} (copy .env.example to .env)")
        return False

    from langchain_core.messages import ToolMessage
    from langchain_core.tools import tool

    from funding_watch.models import get_model

    llm = get_model()
    ok = True
    print("Endpoint")
    ok &= _step("1. plain call", lambda: repr(llm.invoke([("user", "Reply with the word ready.")]).text[:40]))

    class Deadline(BaseModel):
        kind: str
        due: date

    def structured():
        out = llm.with_structured_output(Deadline).invoke(
            [("system", "Extract the deadline."), ("user", "Letter of intent due 10 Nov 2026.")])
        assert out.due == date(2026, 11, 10), f"expected 2026-11-10, got {out.due}"
        return f"{out.kind} {out.due}"
    ok &= _step("2. structured output", structured)

    @tool
    def days_until(iso_date: str) -> int:
        """Days from 2026-10-06 until the given ISO date."""
        return (date.fromisoformat(iso_date) - date(2026, 10, 6)).days

    def round_trip():
        bound = llm.bind_tools([days_until])
        msgs = [("user", "How many days until 2026-11-10? Use the tool.")]
        first = bound.invoke(msgs)
        assert first.tool_calls, "model did not call the tool"
        result: ToolMessage = days_until.invoke(first.tool_calls[0])
        final = bound.invoke([*msgs, first, result])
        assert "35" in final.text, f"answer did not use the tool result: {final.text[:80]!r}"
        return f"tool said {result.content}; model answered {final.text[:50]!r}"
    ok &= _step("3. tool round trip", round_trip)

    print("Funding source")

    def source():
        from funding_watch.funding.sources import get_source
        src = get_source()
        hits = src.search("research software", 3)
        return f"{src.name}: {len(hits)} results for 'research software'"
    ok &= _step("search", source)

    if s.funding_source != "fixtures":
        def nsf_page():
            from funding_watch.funding.sources import get_source
            rec = get_source().get(s.seminar_opportunity or "NSF 26-525")
            assert rec, "record not found"
            kinds = sorted({d.kind for d in rec.deadlines})
            return f"{rec.number}: {', '.join(kinds) or 'no dated deadlines'}"
        ok &= _step("NSF solicitation", nsf_page)

        def awards():
            from funding_watch.funding.sources import get_source
            return f"{len(get_source('nsf').nsf.awards('cyberinfrastructure', 3))} NSF awards"
        ok &= _step("NSF awards", awards)
    print("Slack")

    def slack():
        from funding_watch.slack import (
            get_slack,
            load_teams,
            notifies,
        )
        cfg = load_teams()
        ids = sum(notifies(who) for who in cfg["teams"].values())
        listed = (f"{cfg['channel']}, {ids} of {len(cfg['teams'])} teams mentioned by Slack ID"
                  + (", digest" if cfg["digest"] else ""))
        from funding_watch.config import get_settings
        listened = "; mentions: " + ("SLACK_APP_TOKEN set, `funding-watch slack` listens" if get_settings().slack_app_token
                                     else "no SLACK_APP_TOKEN")
        client = get_slack()
        if client.mode == "practice":
            return f"practice mode, nothing is sent ({listed}); SLACK_MODE=live to post{listened}"
        return f"live as {client.whoami()} ({listed}){listened}"
    ok &= _step("NIH watch", slack)
    print("All checks passed." if ok else "Some checks failed.")
    return ok

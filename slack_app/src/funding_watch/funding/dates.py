"""Date arithmetic for funding workflows. Plain Python: no model calls.

Every day count is relative to ``today()``: the real date, unless ``DEMO_TODAY``
pins one (e.g. DEMO_TODAY=2026-10-06, so day counts stay reproducible).
"""

from __future__ import annotations

from datetime import date, timedelta

from funding_watch.config import get_settings
from funding_watch.funding.schemas import Opportunity, OpportunityFacts


def today() -> date:
    return get_settings().today()


def days_left(d: date, *, on: date | None = None) -> int:
    return (d - (on or today())).days


def _dated(facts: OpportunityFacts) -> list[tuple[str, date | None]]:
    return [("letter of intent", facts.loi_due), ("preliminary proposal", facts.prelim_due),
            ("full application", facts.full_due)]


def deadline_rows(facts: OpportunityFacts, *, on: date | None = None) -> list[dict]:
    """Each deadline with its type and the number of days left."""
    on = on or today()
    rows = [
        {"kind": kind, "date": d.isoformat(), "days_left": days_left(d, on=on)}
        for kind, d in _dated(facts)
        if d
    ]
    if facts.rolling:
        rows.append({"kind": "rolling", "date": None, "days_left": None})
    return rows


def date_issues(facts: OpportunityFacts, *, on: date | None = None) -> list[str]:
    """Problems a person should see before relying on the extracted facts."""
    on = on or today()
    issues = []
    for kind, d in _dated(facts):
        kind = kind.capitalize()
        if d and abs(d.year - on.year) > 5:
            issues.append(f"{kind} date {d.isoformat()} looks implausible; check the extraction")
        elif d and d < on:
            issues.append(f"{kind} deadline {d.isoformat()} has already passed")
    for kind, early in (("Letter of intent", facts.loi_due), ("Preliminary proposal", facts.prelim_due)):
        if early and facts.full_due and early > facts.full_due:
            issues.append(f"{kind} is due after the application")
    if not (facts.loi_due or facts.prelim_due or facts.full_due or facts.rolling):
        issues.append("No deadline found in the text")
    if facts.award_max is None:
        issues.append("Award amount not stated")
    return issues


def record_deadlines(record: Opportunity, *, on: date | None = None) -> list[dict]:
    on = on or today()
    return [
        {"kind": d.kind, "date": d.date.isoformat(), "days_left": days_left(d.date, on=on)}
        for d in sorted(record.deadlines, key=lambda d: d.date)
    ]


def opportunity_status(record: Opportunity, *, on: date | None = None) -> str:
    """"open", "closed" or "rolling", decided by date comparison only."""
    on = on or today()
    if record.rolling:
        return "rolling"
    if not record.deadlines:
        return "unknown"
    return "open" if max(d.date for d in record.deadlines) >= on else "closed"


def next_deadline(record: Opportunity, *, on: date | None = None) -> dict | None:
    on = on or today()
    upcoming = [d for d in record_deadlines(record, on=on) if d["days_left"] >= 0]
    return upcoming[0] if upcoming else None


def backward_milestones(facts: OpportunityFacts, *, on: date | None = None) -> list[dict]:
    """Preparation milestones counted back from each deadline.

    Owners are left empty: assigning people is a human decision.
    """
    on = on or today()
    first = min((d for _, d in _dated(facts) if d), default=None)
    steps: list[tuple[str, date | None]] = []
    confirm_by = on + timedelta(days=14)
    if first:
        confirm_by = min(confirm_by, first - timedelta(days=7))
    steps.append(("Confirm eligibility with research administration", confirm_by))
    if facts.loi_due:
        steps.append(("Letter of intent draft ready for internal review", facts.loi_due - timedelta(days=7)))
        steps.append(("Submit letter of intent", facts.loi_due))
    if facts.prelim_due:
        steps.append(("Preliminary proposal draft ready for internal review", facts.prelim_due - timedelta(days=10)))
        steps.append(("Submit preliminary proposal", facts.prelim_due))
    if facts.full_due:
        steps.append(("Full application draft ready for internal review", facts.full_due - timedelta(days=14)))
        steps.append(("Submit full application", facts.full_due))
    if facts.rolling and not first:
        steps.append(("Rolling deadline: choose a target submission date", None))
    return [
        {
            "step": step,
            "due": d.isoformat() if d else None,
            "days_left": days_left(d, on=on) if d else None,
            "overdue": bool(d and d < on),
            "owner": None,
        }
        for step, d in steps
    ]

"""Data models for the funding storyline.

Two kinds of objects are kept apart on purpose:

* ``Opportunity`` is a *source record*. It comes from a fixture file or an
  official API, never from model prose.
* ``OpportunityFacts`` is what a model *extracts* from announcement text. Code
  checks it (dates, order, missing values) before anything relies on it.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Annotated, Any

from pydantic import BaseModel, BeforeValidator, Field

_DATE_FORMATS = ("%Y-%m-%d", "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y", "%b %d %Y", "%B %d %Y", "%m/%d/%Y")


def parse_date(value: Any) -> Any:
    """Accept ISO dates and common written forms ("10 Nov 2026", "November 10, 2026").

    Models asked for a date do not always return ISO 8601. Parsing here, in code,
    is cheaper and more reliable than asking again. Anything unparseable is passed
    through so Pydantic reports it.
    """
    if not isinstance(value, str):
        return value
    text = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", value.strip().rstrip("."))
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return value


FlexibleDate = Annotated[date, BeforeValidator(parse_date)]


class Deadline(BaseModel):
    kind: str = Field(description='Deadline type, e.g. "letter of intent" or "full application"')
    date: date


class Opportunity(BaseModel):
    """One funding announcement, as published by its source."""

    id: str
    title: str
    agency: str = ""
    summary: str = ""
    keywords: list[str] = []
    eligibility: list[str] = []
    deadlines: list[Deadline] = []
    rolling: bool = False
    award_max: int | None = None
    url: str | None = None
    text: str = ""
    number: str | None = None  # agency opportunity number, when it differs from id
    agency_code: str = ""
    details_url: str | None = None  # the agency's own page, when the source links one
    source: str = "fixtures"


class ResearchGroup(BaseModel):
    """One research group of the applicant, as its website describes it (data/research_profiles)."""

    id: str
    name: str
    focus: str
    expertise: list[str] = []
    projects: list[str] = []
    search_terms: list[str] = []  # fixed queries for workflows that search without a model
    url: str | None = None


class OpportunityFacts(BaseModel):
    """Requirements extracted from one announcement. Unknowns stay empty."""

    id: str = Field(description="Opportunity identifier only, e.g. DEMO-101 (not the title)")
    purpose: str = Field(description="What the program funds, in one sentence")
    eligible: list[str] = Field(description="Applicant types that may apply")
    loi_due: FlexibleDate | None = Field(description="Letter-of-intent deadline as YYYY-MM-DD, if any")
    prelim_due: FlexibleDate | None = Field(default=None, description="Preliminary-proposal deadline as YYYY-MM-DD, if any")
    full_due: FlexibleDate | None = Field(description="Full-application (full proposal) deadline as YYYY-MM-DD, if any")
    rolling: bool = Field(default=False, description="True only if applications are accepted on a rolling basis")
    award_max: int | None = Field(default=None, description="Maximum award in dollars. Leave empty unless the text states it")

    @classmethod
    def coerce(cls, value: Any) -> "OpportunityFacts":
        """Accept an instance or a plain dict (e.g. JSON input from LangGraph Studio)."""
        return value if isinstance(value, cls) else cls.model_validate(value)


def deadline_stage(kind: str) -> str:
    """Group a source's deadline label: "loi", "prelim" or "full"."""
    kind = kind.lower()
    if "intent" in kind:
        return "loi"
    if "preliminary" in kind or "pre-proposal" in kind or "preproposal" in kind:
        return "prelim"
    return "full"


def facts_from_record(record: Opportunity, *, on: date | None = None) -> OpportunityFacts:
    """Build facts directly from a structured record (no model involved).

    When a stage has several dates (e.g. NSF's twice-yearly deadlines), the next
    upcoming one is used; if all have passed, the latest.
    """
    if on is None:
        from funding_watch.config import get_settings

        on = get_settings().today()
    by_stage: dict[str, list[date]] = {}
    for d in record.deadlines:
        by_stage.setdefault(deadline_stage(d.kind), []).append(d.date)

    def pick(stage: str) -> date | None:
        dates = sorted(by_stage.get(stage, []))
        return next((d for d in dates if d >= on), dates[-1] if dates else None)

    return OpportunityFacts(
        id=record.number or record.id,
        purpose=record.summary,
        eligible=record.eligibility,
        loi_due=pick("loi"),
        prelim_due=pick("prelim"),
        full_due=pick("full"),
        rolling=record.rolling,
        award_max=record.award_max,
    )

"""Funding-opportunity domain: records, sources, date math, deduplication and tools."""

import json

from funding_watch.config import DATA_DIR
from funding_watch.funding.schemas import ResearchGroup
from funding_watch.funding.sources import get_record


def load_profile(name: str = "renci") -> str:
    """A research-interest profile from data/research_profiles/<name>.md."""
    return (DATA_DIR / "research_profiles" / f"{name}.md").read_text().strip()


def load_groups(name: str = "renci") -> list[ResearchGroup]:
    """An organization's research groups from data/research_profiles/<name>_groups.json."""
    data = json.loads((DATA_DIR / "research_profiles" / f"{name}_groups.json").read_text())
    return [ResearchGroup(**g) for g in data["groups"]]


def announcement_text(opportunity_id: str) -> str:
    """The announcement text of one record from the configured source."""
    rec = get_record(opportunity_id)
    return rec.text or rec.summary

"""Where funding records come from.

``FUNDING_SOURCE`` selects the backend:

* ``fixtures`` (default): the fictional records in ``data/funding/opportunities.json``.
  Deterministic and offline, so runs are reproducible.
* ``live`` (alias ``grantsgov``): real opportunities from every federal agency
  via Grants.gov. NSF records are completed from the NSF solicitation page,
  which has the full deadline schedule, and NIH records from the full notice of
  funding opportunity attached on Grants.gov, which says what is funded.
* ``nsf``: the same, limited to NSF.

All return ``Opportunity`` records, so tools and graphs never need to know
which one is active. No API keys are needed.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Protocol

from funding_watch.config import DATA_DIR, get_settings
from funding_watch.funding.dedupe import normalize_id
from funding_watch.funding.grantsgov import (
    GrantsGovClient,
    record_from_fetch,
    record_from_hit,
)
from funding_watch.funding.nih import NIHClient
from funding_watch.funding.nsf import NSFClient
from funding_watch.funding.schemas import Opportunity

FIXTURE_PATH = DATA_DIR / "funding" / "opportunities.json"


class FundingSource(Protocol):
    name: str

    def search(self, query: str, limit: int = 5) -> list[Opportunity]: ...

    def get(self, opportunity_id: str) -> Opportunity | None: ...


# ---------------------------------------------------------------- fixtures

_STOPWORDS = set(
    "a an and are as at be by for from funding fund funds grant grants how in into is it of on or "
    "our support supports that the their this to tools tool we what which with".split()
)


def _terms(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    # crude stemming so "pipelines" matches "pipeline" and "imaging" matches "image"
    return {re.sub(r"(ing|es|s)$", "", w) or w for w in words if w not in _STOPWORDS and len(w) > 1}


class FixtureSource:
    """Keyword search over a local JSON file of opportunity records."""

    name = "fixtures"

    def __init__(self, path: Path = FIXTURE_PATH):
        data = json.loads(Path(path).read_text())
        self.records = {normalize_id(r["id"]): Opportunity(**r) for r in data["opportunities"]}

    def search(self, query: str, limit: int = 5) -> list[Opportunity]:
        q = _terms(query)
        scored = []
        for rec in self.records.values():
            strong = _terms(" ".join([rec.title, *rec.keywords]))
            weak = _terms(rec.summary + " " + rec.text)
            score = 3 * len(q & strong) + len(q & (weak - strong))
            if score >= 3:  # at least one title/keyword match, or several body matches
                scored.append((score, rec))
        scored.sort(key=lambda pair: -pair[0])
        return [rec for _, rec in scored[:limit]]

    def get(self, opportunity_id: str) -> Opportunity | None:
        return self.records.get(normalize_id(opportunity_id))


# ---------------------------------------------------------------- live

class GrantsGovSource:
    """Live records from Grants.gov, optionally limited to some agencies (e.g. "NSF").

    IDs are Grants.gov opportunity IDs; ``get`` also accepts opportunity
    numbers such as "NSF 26-525" or "RFA-OD-26-034".
    """

    def __init__(self, agencies: str = "", name: str = "grantsgov"):
        self.agencies = agencies
        self.name = name
        self.grants = GrantsGovClient()
        self.nsf = NSFClient()
        self.nih = NIHClient()
        self._records: dict[str, Opportunity] = {}  # full records are fetched once per process

    def search(self, query: str, limit: int = 5, agencies: str | None = None) -> list[Opportunity]:
        hits = self.grants.search(query, agencies=self.agencies if agencies is None else agencies, rows=limit)
        return [record_from_hit(h, self.name) for h in hits]

    def get(self, opportunity_id: str) -> Opportunity | None:
        key = str(opportunity_id).strip()
        if not key:
            return None
        oid = key if key.isdigit() else self.grants.find_id(key)
        if oid is None:
            return None
        if oid not in self._records:
            data = self.grants.fetch(oid)
            if not data:
                return None
            record = record_from_fetch(data, self.name)
            if record.agency_code == "NSF" and record.details_url:
                record = self.with_nsf_page(record)
            elif record.agency_code.startswith("HHS-NIH"):
                record = self.with_nih_nofo(record, data)
            self._records[oid] = record
        return self._records[oid]

    def with_nih_nofo(self, record: Opportunity, data: dict) -> Opportunity:
        """Replace Grants.gov's short synopsis with the NOFO's purpose and program description (Section I)."""
        nofo = self.nih.read_nofo(data)
        if nofo is None:  # a forecast, or no HTML announcement: keep the synopsis
            return record
        note = record.text.partition("\nDeadline note: ")[2]
        return record.model_copy(update={"text": nofo.text + (f"\nDeadline note: {note}" if note else ""),
                                         "details_url": nofo.url})

    def with_nsf_page(self, record: Opportunity) -> Opportunity:
        """Replace Grants.gov's single close date with the solicitation's full schedule."""
        page = self.nsf.read_page(record.details_url)
        if page is None or not page.text:
            return record.model_copy(update={"text": record.text + "\n(NSF solicitation page unavailable.)"})
        deadlines = page.deadlines or record.deadlines
        if page.deadlines and record.deadlines and max(d.date for d in record.deadlines) > max(d.date for d in page.deadlines):
            deadlines = [*page.deadlines, *record.deadlines]  # recurring: the page lists past cycles, Grants.gov the next
        return record.model_copy(update={
            "text": page.text,
            "deadlines": deadlines,
            "rolling": (page.rolling or record.rolling) and not deadlines,
            "award_max": page.award_max or record.award_max,
            "details_url": page.url,
        })


# ---------------------------------------------------------------- selection

_SOURCES = {
    "fixtures": FixtureSource,
    "grantsgov": GrantsGovSource,
    "nsf": lambda: GrantsGovSource(agencies="NSF", name="nsf"),
}
_ALIASES = {"live": "grantsgov", "real": "grantsgov"}


def source_name(name: str | None = None) -> str:
    name = re.sub(r"[^a-z]", "", (name or get_settings().funding_source).lower())
    name = _ALIASES.get(name, name)
    if name not in _SOURCES:
        raise ValueError(f"Unknown FUNDING_SOURCE {name!r}; choose fixtures, live or nsf")
    return name


@lru_cache(maxsize=None)
def _cached(name: str) -> FundingSource:
    return _SOURCES[name]()


def get_source(name: str | None = None) -> FundingSource:
    """The configured funding source (``FUNDING_SOURCE``), created once per name."""
    return _cached(source_name(name))


def get_record(opportunity_id: str) -> Opportunity:
    """Read one record from the configured source, or raise KeyError."""
    record = get_source().get(opportunity_id)
    if record is None:
        raise KeyError(f"No opportunity with id {opportunity_id!r} in source {get_source().name!r}")
    return record

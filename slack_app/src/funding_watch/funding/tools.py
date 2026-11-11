"""LangChain tools for finding and reading funding opportunities.

Each tool returns two things (``response_format="content_and_artifact"``):

* ``content``: compact JSON text the model reads.
* ``artifact``: the same rows as Python data, kept on the ToolMessage so code
  (e.g. ``ids_from_tool_results``) can use identifiers without parsing prose.

Dates, statuses and day counts are computed here in code, never by the model.

* ``search_opportunities`` / ``read_opportunity``: the configured ``FUNDING_SOURCE``.
* ``search_grants_gov``: live Grants.gov, every federal agency.
* ``search_nsf_funding``: live NSF funding opportunities.
* ``search_nsf_awards``: grants NSF has already made, to show what gets funded.

``funding_tools()`` picks the set that matches the configured source.
"""

from __future__ import annotations

import json

from langchain_core.tools import tool

from funding_watch.funding.dates import next_deadline, opportunity_status, record_deadlines
from funding_watch.funding.schemas import Opportunity
from funding_watch.funding.sources import get_source, source_name


def search_row(rec: Opportunity) -> dict:
    row = {
        "id": rec.id,
        "number": rec.number,
        "title": rec.title,
        "agency": rec.agency,
        "summary": rec.summary,
        "status": opportunity_status(rec),
        "next_deadline": next_deadline(rec),
    }
    return {k: v for k, v in row.items() if v or k in ("status", "next_deadline")}


def record_row(rec: Opportunity) -> dict:
    return {
        "id": rec.id,
        "number": rec.number,
        "title": rec.title,
        "agency": rec.agency,
        "url": rec.url,
        "agency_page": rec.details_url,
        "eligibility": rec.eligibility,
        "deadlines": record_deadlines(rec),
        "rolling": rec.rolling,
        "status": opportunity_status(rec),
        "award_max": rec.award_max,
        "announcement": rec.text or rec.summary,
    }


def _search_result(records: list[Opportunity], query: str) -> tuple[str, list[dict]]:
    rows = [search_row(r) for r in records]
    if not rows:
        return f"No opportunities matched {query!r}. Try broader or different keywords.", []
    return json.dumps(rows, indent=1), rows


def find_record(opportunity_id: str) -> Opportunity | None:
    """The configured source first; live Grants.gov for IDs the fixtures do not have."""
    record = get_source().get(opportunity_id)
    if record is None and source_name() == "fixtures":
        record = get_source("live").get(opportunity_id)
    return record


@tool(response_format="content_and_artifact")
def search_opportunities(query: str) -> tuple[str, list[dict]]:
    """Search funding announcements by keywords. Returns ids, titles, one-line summaries,
    status (open / closed / rolling) and the next deadline. Use read_opportunity for details."""
    return _search_result(get_source().search(query, limit=5), query)


@tool(response_format="content_and_artifact")
def search_grants_gov(query: str, agency: str = "") -> tuple[str, list[dict]]:
    """Search open and forecasted federal funding opportunities on Grants.gov by keywords.
    Optionally limit to one agency code, e.g. NSF, HHS-NIH11 (NIH), DOE, NASA.
    Returns ids, numbers, titles, agencies, status and the next deadline. Use read_opportunity for details."""
    return _search_result(get_source("live").search(query, limit=6, agencies=agency.strip().upper()), query)


@tool(response_format="content_and_artifact")
def search_nsf_funding(query: str) -> tuple[str, list[dict]]:
    """Search open NSF funding opportunities (solicitations and program descriptions) by keywords.
    Returns ids, NSF numbers, titles, status and the next deadline. Use read_opportunity for the
    full solicitation, including letter-of-intent and preliminary-proposal dates."""
    return _search_result(get_source("nsf").search(query, limit=6), query)


@tool(response_format="content_and_artifact")
def search_nsf_awards(query: str) -> tuple[str, list[dict]]:
    """Search grants NSF has already awarded, newest first, by keywords. Shows which programs fund
    similar work, at what size, and where. These are past awards, not open opportunities."""
    rows = get_source("nsf").nsf.awards(query, limit=5)
    if not rows:
        return f"No NSF awards matched {query!r}. Try fewer or different keywords.", []
    return json.dumps(rows, indent=1), rows


@tool(response_format="content_and_artifact")
def read_opportunity(id: str) -> tuple[str, list[dict]]:
    """Return one full announcement record: eligibility, every deadline with its type,
    award ceiling (null when not stated), official URL and the announcement text.
    Accepts an id from a search result or an opportunity number such as "NSF 26-525"."""
    rec = find_record(id)
    if rec is None:
        return f"No opportunity with id {id!r}. Use an id returned by a search tool.", []
    row = record_row(rec)
    return json.dumps(row, indent=1), [row]


FIXTURE_TOOLS = [search_opportunities, read_opportunity]
LIVE_TOOLS = [search_grants_gov, search_nsf_funding, read_opportunity, search_nsf_awards]
NSF_TOOLS = [search_nsf_funding, read_opportunity, search_nsf_awards]


def funding_tools(source: str | None = None) -> list:
    """The tools that match ``FUNDING_SOURCE``: fixtures, live (Grants.gov + NSF) or NSF only."""
    return {"fixtures": FIXTURE_TOOLS, "grantsgov": LIVE_TOOLS, "nsf": NSF_TOOLS}[source_name(source)]

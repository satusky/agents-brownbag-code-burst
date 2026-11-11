"""Bookkeeping that belongs in code: identifiers from tool results and deduplication."""

from __future__ import annotations

from collections.abc import Iterable

from langchain_core.messages import BaseMessage, ToolMessage


def normalize_id(value: str) -> str:
    return value.strip().upper()


def ids_from_tool_results(messages: Iterable[BaseMessage]) -> list[dict]:
    """Opportunity IDs that tools actually returned, in first-seen order.

    Reads the structured ``artifact`` of each ToolMessage, so an ID the model
    merely mentions in prose is never counted. ``opened`` is True when the full
    record was read, False when it was only seen in search results.
    """
    seen: dict[str, dict] = {}
    for msg in messages:
        if not isinstance(msg, ToolMessage) or not msg.artifact:
            continue
        rows = msg.artifact if isinstance(msg.artifact, list) else [msg.artifact]
        opened = msg.name == "read_opportunity"
        for row in rows:
            if isinstance(row, dict) and row.get("id"):
                key = normalize_id(row["id"])
                entry = seen.setdefault(key, {"id": key, "opened": False})
                entry["opened"] = entry["opened"] or opened
                if row.get("number"):
                    entry["number"] = row["number"]  # e.g. "NSF 26-506" for a Grants.gov id
    return list(seen.values())


def dedupe_findings(findings: Iterable[dict]) -> list[dict]:
    """Group findings by opportunity ID, keeping which themes found each one."""
    grouped: dict[str, dict] = {}
    for f in findings:
        key = normalize_id(f["id"])
        g = grouped.setdefault(key, {"id": key, "found_by": [], "opened": False})
        if f.get("number"):
            g["number"] = f["number"]
        if f.get("theme") and f["theme"] not in g["found_by"]:
            g["found_by"].append(f["theme"])
        g["opened"] = g["opened"] or bool(f.get("opened"))
    return sorted(grouped.values(), key=lambda g: -len(g["found_by"]))


STRETCH = ("natural fit", "moderate stretch", "major stretch", "not a fit")  # least to most new work


def stretch_rank(stretch: str | None) -> int:
    return STRETCH.index(stretch) if stretch in STRETCH else len(STRETCH)


def merge_findings(findings: Iterable[dict]) -> list[dict]:
    """One row per opportunity: every group that found it, and the smallest stretch among them.

    A finding is ``{"group", "id", "stretch", "overlap", ...}`` plus source fields
    (number, title, status, next_deadline) copied from tool results. A row takes
    its source fields from one finding, preferring a record read in full over a
    search result, so a row never mixes the two. Rows are sorted by stretch, then
    by how many groups found the opportunity.
    """
    findings = list(findings)
    source: dict[str, dict] = {}
    for f in sorted(findings, key=lambda f: not f.get("opened")):  # a record read in full wins
        source.setdefault(normalize_id(f["id"]), f)
    grouped: dict[str, dict] = {}
    for f in findings:
        key, src = normalize_id(f["id"]), source[normalize_id(f["id"])]
        g = grouped.setdefault(key, {"id": key, **{k: src.get(k) for k in ("number", "title", "status", "next_deadline")},
                                     "groups": [], "opened": bool(src.get("opened"))})
        if not any(x["group"] == f.get("group") for x in g["groups"]):
            g["groups"].append({"group": f.get("group"), "stretch": f.get("stretch"), "overlap": f.get("overlap", "")})
    for g in grouped.values():
        g["stretch"] = min((x["stretch"] for x in g["groups"]), key=stretch_rank)
    return sorted(grouped.values(), key=lambda g: (stretch_rank(g["stretch"]), -len(g["groups"])))

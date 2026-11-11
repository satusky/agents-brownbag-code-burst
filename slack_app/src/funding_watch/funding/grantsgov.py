"""Grants.gov REST API client (no key required).

* ``search2``: keyword search across every federal agency, optionally filtered
  by agency code (e.g. ``NSF``, ``HHS-NIH11``).
* ``fetchOpportunity``: one full record (synopsis or forecast).

Docs: https://www.grants.gov/api/api-guide
"""

from __future__ import annotations

import html
import re
from datetime import date, datetime

import httpx

from funding_watch.funding.schemas import Deadline, Opportunity

API = "https://api.grants.gov/v1/api"
OPEN = "forecasted|posted"
ANY_STATUS = "forecasted|posted|closed|archived"


def parse_date(value: str | None) -> date | None:
    """Grants.gov dates come as "2027-07-27-00-00-00", "07/27/2027" or "Jul 27, 2027 12:00:00 AM EDT"."""
    value = (value or "").strip()
    if re.match(r"\d{4}-\d{2}-\d{2}", value):
        return date.fromisoformat(value[:10])
    for fmt, part in (("%m/%d/%Y", value), ("%b %d, %Y", " ".join(value.split()[:3]))):
        try:
            return datetime.strptime(part, fmt).date()
        except ValueError:
            continue
    return None


def real_close(d: date | None) -> date | None:
    """None for the far-future placeholder (e.g. 2076) Grants.gov gives programs that accept proposals anytime."""
    return d if d and d.year < date.today().year + 25 else None


def html_to_text(markup: str | None) -> str:
    """Strip tags, keeping block elements as line breaks."""
    text = re.sub(r"<(script|style)\b.*?</\1>", " ", markup or "", flags=re.S | re.I)
    text = re.sub(r"</?(p|div|li|ul|ol|h[1-6]|br|tr|table|dt|dd|section)\b[^>]*>", "\n", text, flags=re.I)
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    text = re.sub(r"[ \t\xa0]+", " ", text)
    return re.sub(r"\s*\n\s*", "\n", text).strip()


def money(value) -> int | None:
    try:
        return int(float(str(value).replace(",", "").replace("$", "")))
    except (TypeError, ValueError):
        return None


POSTED_WINDOWS = (3, 7, 14, 21, 28, 35, 42, 49, 56)  # the "posted in the last N days" filters search2 accepts


def posted_window(days: int) -> int:
    """The smallest Grants.gov posted-date window that covers ``days`` (at most 8 weeks)."""
    return next((w for w in POSTED_WINDOWS if w >= days), POSTED_WINDOWS[-1])


def display_number(number: str | None, agency_code: str = "") -> str | None:
    """NSF lists solicitations on Grants.gov as "26-525"; NSF itself says "NSF 26-525"."""
    if number and agency_code == "NSF" and re.fullmatch(r"\d{2}-\d{3}", number):
        return f"NSF {number}"
    return number


class GrantsGovClient:
    def __init__(self, timeout: float = 30.0):
        self.http = httpx.Client(base_url=API, timeout=timeout)
        self._agencies: dict[str, list[str]] | None = None
        self._labels: dict[str, str] = {}

    def _post(self, path: str, payload: dict) -> dict:
        resp = self.http.post(path, json=payload)
        resp.raise_for_status()
        body = resp.json()
        if body.get("errorcode", 0) != 0:
            raise RuntimeError(f"Grants.gov: {body.get('msg')}")
        return body.get("data") or {}

    def search(self, keyword: str = "", *, agencies: str = "", rows: int = 5,
               statuses: str = OPEN, number: str = "", posted_within: int | None = None) -> list[dict]:
        """Raw search hits: id, number, title, agency, agencyCode, openDate, closeDate, oppStatus, docType.

        ``agencies`` takes Grants.gov codes ("HHS-NIH11|NSF") or common short names ("NIH", "DOE").
        ``posted_within`` keeps opportunities posted in the last N days. Grants.gov only filters by
        whole weeks (3 days, then 1 to 8 weeks), so N is rounded up to the next window it offers.
        """
        payload = {"keyword": keyword, "rows": rows, "oppStatuses": statuses}
        if agencies:
            payload["agencies"] = self.agency_codes(agencies)
        if number:
            payload["oppNum"] = number
        if posted_within:
            payload["dateRange"] = str(posted_window(posted_within))
        return self._post("/search2", payload).get("oppHits", [])

    def agency_codes(self, names: str) -> str:
        """Grants.gov filters on exact sub-agency codes ("HHS-NIH11", not "NIH" or "HHS")."""
        if self._agencies is None:
            facet = self._post("/search2", {"keyword": "", "rows": 0, "oppStatuses": OPEN}).get("agencies", [])
            self._agencies = {a["value"]: [s["value"] for s in a.get("subAgencyOptions") or []] for a in facet}
            self._labels = {a["value"]: a.get("label", "") for a in facet}
        codes = []
        for name in filter(None, (n.strip().upper() for n in names.split("|"))):
            if name in self._agencies:  # a department: all of its sub-agencies, and offices listed
                label = self._labels[name]  # separately ("Department of Energy - Office of Science")
                for dept in [name, *(d for d, l in self._labels.items() if label and l.startswith(label + " -"))]:
                    codes += self._agencies[dept] or [dept]
                continue
            subs = [c for cs in self._agencies.values() for c in cs]
            codes += [c for c in subs if c == name or name in c.split("-")[1:] or name in c] or [name]
        return "|".join(dict.fromkeys(codes))

    def fetch(self, opportunity_id: int | str) -> dict:
        return self._post("/fetchOpportunity", {"opportunityId": int(opportunity_id)})

    def find_id(self, number: str) -> str | None:
        """Grants.gov id for an opportunity number such as "NSF 26-525", "26-525" or "RFA-OD-26-034"."""
        number = re.sub(r"^NSF\s+", "", number.strip(), flags=re.I)
        hits = [h for h in self.search(number=number, rows=10, statuses=ANY_STATUS)
                if h.get("number", "").upper() == number.upper()]
        hits.sort(key=lambda h: h.get("oppStatus") != "posted")  # prefer the open listing
        return str(hits[0]["id"]) if hits else None


def record_from_hit(hit: dict, source: str) -> Opportunity:
    raw = parse_date(hit.get("closeDate"))
    close = real_close(raw)
    agency = html.unescape(hit.get("agency", ""))
    number = display_number(hit.get("number"), hit.get("agencyCode", ""))
    return Opportunity(
        id=str(hit["id"]),
        number=number,
        title=html.unescape(hit.get("title", "")),
        agency=agency,
        agency_code=hit.get("agencyCode", ""),
        summary=" · ".join(x for x in (agency, number, hit.get("oppStatus")) if x),
        deadlines=[Deadline(kind="application close date", date=close)] if close else [],
        rolling=bool(raw) and not close,
        url=f"https://www.grants.gov/search-results-detail/{hit['id']}",
        source=source,
    )


def record_from_fetch(data: dict, source: str) -> Opportunity:
    """A full Grants.gov record. Forecasts carry estimated dates, labeled as such."""
    forecast = not data.get("synopsis")
    syn = data.get("synopsis") or data.get("forecast") or {}
    oid = str(data.get("id"))
    if forecast:
        raw = parse_date(syn.get("estApplicationResponseDateStr"))
        kind = "estimated application due date (forecast)"
        body = syn.get("forecastDesc")
    else:
        raw = parse_date(syn.get("responseDateStr") or syn.get("responseDate"))
        kind = "application close date"
        body = syn.get("synopsisDesc")
    close = real_close(raw)
    note = html_to_text(syn.get("responseDateDesc"))
    eligibility = [t.get("description", "") for t in syn.get("applicantTypes") or []]
    if syn.get("applicantEligibilityDesc"):
        eligibility.append(html_to_text(syn["applicantEligibilityDesc"])[:800])
    text = html_to_text(body)
    if note:
        text += f"\nDeadline note: {note}"
    agency_code = syn.get("agencyCode") or data.get("owningAgencyCode", "")
    return Opportunity(
        id=oid,
        number=display_number(data.get("opportunityNumber"), agency_code),
        title=html.unescape(data.get("opportunityTitle", "")),
        agency=syn.get("agencyName", ""),
        agency_code=agency_code,
        summary=text[:280],
        eligibility=[e for e in eligibility if e],
        deadlines=[Deadline(kind=kind, date=close)] if close else [],
        rolling=not close and (bool(raw) or "anytime" in note.lower()),
        award_max=money(syn.get("awardCeiling")),
        url=f"https://www.grants.gov/search-results-detail/{oid}",
        text=text,
        source=source,
        details_url=syn.get("fundingDescLinkUrl"),
    )

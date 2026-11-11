"""NIH: the full notice of funding opportunity (NOFO), attached to its Grants.gov record.

For NIH, Grants.gov keeps only a short synopsis, often the same few sentences
for every opportunity in a consortium (a data center and its clinical centers
read alike). The full NOFO is attached to the Grants.gov record as an HTML file
(folder "Full Announcement"). ``read_nofo`` downloads it and keeps the parts
that say what is funded: the purpose and Section I, the program description.
Forecasts have no NOFO yet, so they keep the synopsis.

No key is needed. Attachments: https://apply07.grants.gov/grantsws/rest/opportunity/att/download/<id>
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import httpx

from funding_watch.funding.grantsgov import html_to_text

ATTACHMENT_URL = "https://apply07.grants.gov/grantsws/rest/opportunity/att/download/{id}"
MAX_DESCRIPTION = 12000  # characters of Section I kept; the rest of a NOFO is application instructions

_SECTION_I = re.compile(r"Section I\.\s*(?:Notice of )?Funding Opportunity Description", re.IGNORECASE)
_SECTION_II = re.compile(r"Section II\.\s*Award Information", re.IGNORECASE)
_PURPOSE = re.compile(r"\nFunding Opportunity Purpose\n(.*?)\n(?:Funding Opportunity Goal|Key Dates|Posted Date)", re.DOTALL)


@dataclass
class Nofo:
    url: str
    purpose: str      # Part 1 "Funding Opportunity Purpose"
    description: str  # Part 2 Section I, the program description

    @property
    def text(self) -> str:
        parts = [self.purpose, self.description]
        return "\n\n".join(p for p in parts if p)


def full_announcement(data: dict) -> dict | None:
    """The HTML "Full Announcement" attachment of a Grants.gov fetchOpportunity record, if it has one."""
    for folder in data.get("synopsisAttachmentFolders") or []:
        for att in folder.get("synopsisAttachments") or []:
            name, kind = att.get("fileName") or "", att.get("mimeType") or ""
            full = "full announcement" in (folder.get("folderName") or "").lower() or "full-announcement" in name.lower()
            if full and ("html" in kind or name.lower().endswith((".html", ".htm"))):
                return att
    return None


def description(text: str) -> str:
    """Section I of an NOFO's text. The heading appears twice (contents, then body): keep the longer span."""
    best = ""
    for m in _SECTION_I.finditer(text):
        end = _SECTION_II.search(text, m.end())
        chunk = text[m.start(): end.start() if end else m.start() + MAX_DESCRIPTION].strip()
        if len(chunk) > len(best):
            best = chunk
    return best[:MAX_DESCRIPTION]


def purpose(text: str) -> str:
    m = _PURPOSE.search(text)
    return f"Funding Opportunity Purpose\n{m.group(1).strip()}" if m else ""


def parse_nofo(markup: str, url: str) -> Nofo:
    text = html_to_text(markup)
    return Nofo(url=url, purpose=purpose(text), description=description(text))


class NIHClient:
    def __init__(self, timeout: float = 30.0):
        self.http = httpx.Client(timeout=timeout, follow_redirects=True)

    def read_nofo(self, data: dict) -> Nofo | None:
        """The full NOFO of a Grants.gov record, or None (a forecast, no HTML attachment, or a failed download)."""
        att = full_announcement(data)
        if att is None:
            return None
        url = ATTACHMENT_URL.format(id=att["id"])
        try:
            resp = self.http.get(url)
            resp.raise_for_status()
        except httpx.HTTPError:
            return None
        nofo = parse_nofo(resp.text, url)
        return nofo if nofo.description else None

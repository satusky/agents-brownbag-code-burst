"""Post messages to Slack: a practice version (nothing is sent) and the live Web API.

``SLACK_MODE`` picks one:

* ``practice`` (default): nothing leaves the machine. Each message is kept in
  ``PracticeSlack.sent``, so a run shows exactly what would have been posted.
* ``live``: ``chat.postMessage`` with ``SLACK_BOT_TOKEN`` (a bot token, ``xoxb-…``).
  The app needs the ``chat:write`` scope and must be invited to the channel
  (``/invite @<app name>``). ``manifest.yaml`` creates such an app.

Both return the same dict for every message, so a graph never needs to know
which one is active: ``{"ok", "mode", "channel", "ts", "error"}``.

``teams.json`` names one channel for every message and who to
mention for each research group. A mention notifies people only when it is a
Slack ID (a user group ``S…`` or members ``U…``); other text is shown as written.
In live mode, ``.slack_posted.json`` records which opportunities were posted,
so a later run does not post them again.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Protocol

from funding_watch.config import PROJECT_ROOT, get_settings

TEAMS_FILE = PROJECT_ROOT / "teams.json"
POSTED_FILE = PROJECT_ROOT / ".slack_posted.json"
SLACK_ID = re.compile(r"[SUW][A-Z0-9]{8,}")  # user group (S…) or member (U…, W…)

HINTS = {  # what to do about the Slack errors people hit while setting up
    "not_in_channel": "invite the app to the channel: /invite @<app name>",
    "channel_not_found": "check the channel in teams.json; a private channel also needs the app invited",
    "invalid_auth": "check SLACK_BOT_TOKEN in .env (the Bot User OAuth Token, xoxb-…)",
    "not_authed": "set SLACK_BOT_TOKEN in .env",
    "missing_scope": "add the chat:write scope, then reinstall the app to the workspace",
    "is_archived": "the channel is archived",
}


def error_text(response) -> str:
    """Slack's error code, with what to do about it, or Slack's own details (e.g. which block is invalid)."""
    code = response.get("error") or "unknown error"
    details = "; ".join((response.get("response_metadata") or {}).get("messages") or [])
    hint = HINTS.get(code) or details
    return f"{code} ({hint})" if hint else code


class Slack(Protocol):
    mode: str

    def post(self, channel: str, text: str, blocks: list[dict] | None = None) -> dict: ...


def load_teams(path: Path = TEAMS_FILE) -> dict:
    """``{"channel": channel, "teams": {group id: mention}, "digest": bool}``."""
    data = json.loads(Path(path).read_text())
    return {"channel": data["channel"], "teams": data.get("teams", {}), "digest": bool(data.get("digest", True))}


def mention(who: str | list[str] | None) -> str:
    """Slack mrkdwn for a team: IDs become mentions that notify; any other text is shown as written."""
    if isinstance(who, list):
        return " ".join(m for m in map(mention, who) if m)
    who = (who or "").strip()
    if SLACK_ID.fullmatch(who):
        return f"<!subteam^{who}>" if who.startswith("S") else f"<@{who}>"
    return who.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def notifies(who: str | list[str] | None) -> bool:
    """Whether ``mention(who)`` notifies anyone: every entry is a Slack ID."""
    ids = who if isinstance(who, list) else [who]
    return bool(ids) and all(SLACK_ID.fullmatch((w or "").strip()) for w in ids)


class PracticeSlack:
    """Keeps every message instead of sending it."""

    mode = "practice"

    def __init__(self):
        self.sent: list[dict] = []

    def post(self, channel: str, text: str, blocks: list[dict] | None = None) -> dict:
        result = {"ok": True, "mode": self.mode, "channel": channel, "ts": None, "error": None}
        self.sent.append({**result, "text": text, "blocks": blocks})
        return result


class LiveSlack:
    """chat.postMessage through slack_sdk, retrying when Slack rate-limits."""

    mode = "live"

    def __init__(self, token: str):
        from slack_sdk import WebClient
        from slack_sdk.http_retry.builtin_handlers import RateLimitErrorRetryHandler

        self.client = WebClient(token=token)
        self.client.retry_handlers.append(RateLimitErrorRetryHandler(max_retry_count=2))

    def post(self, channel: str, text: str, blocks: list[dict] | None = None) -> dict:
        from slack_sdk.errors import SlackApiError

        try:
            resp = self.client.chat_postMessage(channel=channel, text=text, blocks=blocks,
                                                unfurl_links=False, unfurl_media=False)
            return {"ok": True, "mode": self.mode, "channel": channel, "ts": resp.get("ts"), "error": None}
        except SlackApiError as exc:
            return {"ok": False, "mode": self.mode, "channel": channel, "ts": None, "error": error_text(exc.response)}

    def whoami(self) -> str:
        auth = self.client.auth_test()
        return f"{auth.get('user')} in {auth.get('team')}"


def get_slack() -> Slack:
    """The configured Slack: practice unless ``SLACK_MODE=live``."""
    s = get_settings()
    if s.slack_mode == "practice":
        return PracticeSlack()
    if s.slack_mode != "live":
        raise ValueError(f"Unknown SLACK_MODE {s.slack_mode!r}; choose practice or live")
    if not s.slack_bot_token:
        raise RuntimeError("SLACK_MODE=live needs SLACK_BOT_TOKEN in .env (see README.md)")
    return LiveSlack(s.slack_bot_token)


# ----------------------------------------------------------------- what was already posted (live only)

def posted_ids(path: Path = POSTED_FILE) -> dict[str, dict]:
    """Opportunity id → {team, channel, posted}, for every opportunity a live run posted."""
    try:
        return json.loads(Path(path).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def record_posted(items: dict[str, dict], path: Path = POSTED_FILE) -> None:
    """Remember ``{opportunity id: {team, channel}}`` so later runs skip them."""
    if not items:
        return
    seen = posted_ids(path)
    stamp = datetime.now().isoformat(timespec="seconds")
    seen.update({oid: {**where, "posted": stamp} for oid, where in items.items()})
    Path(path).write_text(json.dumps(seen, indent=1, sort_keys=True))

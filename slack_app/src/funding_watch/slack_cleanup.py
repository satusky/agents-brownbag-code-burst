"""Delete what the bot posted in a channel, when you are done testing.

    uv run funding-watch slack-cleanup                 # list the bot's messages in the channel; deletes nothing
    uv run funding-watch slack-cleanup --yes           # delete them
    uv run funding-watch slack-cleanup --yes --forget  # and clear .slack_posted.json, so the next pass posts again
    uv run funding-watch slack-cleanup --days 1        # only the last day; --channel picks another channel

It finds the bot's own messages, including its replies in threads under your
mentions, and deletes them with chat.delete. A bot token can only delete what
that bot posted, so nobody else's messages are touched (your mentions stay; you
can delete those yourself). Reading the channel needs the history and read
scopes in manifest.yaml. Uses SLACK_BOT_TOKEN whatever SLACK_MODE says.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from funding_watch.config import get_settings
from funding_watch.slack import HINTS, POSTED_FILE, load_teams

CHANNEL_ID = re.compile(r"[CG][A-Z0-9]{8,}")
NOT_POSTS = {"channel_join", "channel_leave"}  # Slack's notices about the bot, not messages it posted
SHOWN = 5


def make_client(token: str):
    from slack_sdk import WebClient
    from slack_sdk.http_retry.builtin_handlers import RateLimitErrorRetryHandler

    client = WebClient(token=token)
    client.retry_handlers.append(RateLimitErrorRetryHandler(max_retry_count=5))
    return client


def paged(method, key: str, **kwargs):
    """Every item from a cursor-paginated Web API method (each page is one response)."""
    for page in method(**kwargs):
        yield from page.get(key) or []


def channel_id(client, channel: str) -> str:
    """A channel ID as given, or the ID of a channel name such as #brown-bag-demo."""
    if CHANNEL_ID.fullmatch(channel):
        return channel
    name = channel.lstrip("#")
    for c in paged(client.conversations_list, "channels", types="public_channel,private_channel",
                   exclude_archived=True, limit=1000):
        if c["name"] == name:
            return c["id"]
    raise LookupError(f"The bot sees no channel named #{name}. Invite it, or pass the channel ID with --channel "
                      "(channel name → About → Channel ID).")


def bot_messages(client, channel: str, me: dict, oldest: float | None = None) -> list[dict]:
    """The bot's messages in ``channel``: its posts, and its replies in any thread."""

    def mine(m: dict) -> bool:
        return (m.get("bot_id") == me["bot_id"] or m.get("user") == me["user_id"]) and m.get("subtype") not in NOT_POSTS

    found: dict[str, dict] = {}
    since = {"oldest": f"{oldest:.6f}"} if oldest else {}
    for m in paged(client.conversations_history, "messages", channel=channel, limit=200, **since):
        if mine(m):
            found[m["ts"]] = m
        if m.get("reply_count"):  # a thread: the bot answers mentions there
            for r in paged(client.conversations_replies, "messages", channel=channel, ts=m["ts"], limit=200):
                if r["ts"] != m["ts"] and mine(r):
                    found[r["ts"]] = r
    return sorted(found.values(), key=lambda m: float(m["ts"]))


def delete(client, channel: str, messages: list[dict]) -> tuple[int, list[str]]:
    """(deleted, errors). A message already gone counts as deleted."""
    from slack_sdk.errors import SlackApiError

    deleted, errors = 0, []
    for m in messages:
        try:
            client.chat_delete(channel=channel, ts=m["ts"])
        except SlackApiError as exc:
            code = exc.response.get("error", str(exc))
            if code != "message_not_found":
                errors.append(code)
                continue
        deleted += 1
    return deleted, errors


def describe(m: dict) -> str:
    when = datetime.fromtimestamp(float(m["ts"])).strftime("%Y-%m-%d %H:%M")
    text = (m.get("text") or "").splitlines()[0] if m.get("text") else "(no text)"
    return f"{when}  {'reply  ' if m.get('thread_ts') not in (None, m['ts']) else ''}{text[:90]}"


def cleanup(channel: str | None = None, days: int | None = None, yes: bool = False, forget: bool = False) -> int:
    """List (and with ``yes``, delete) the bot's messages in a channel. Returns an exit code."""
    from slack_sdk.errors import SlackApiError

    token = get_settings().slack_bot_token
    if not token:
        print("slack-cleanup needs SLACK_BOT_TOKEN in .env")
        return 1
    client = make_client(token)
    name = channel or load_teams()["channel"]
    try:
        auth = client.auth_test()
        me = {"user_id": auth["user_id"], "bot_id": auth.get("bot_id")}
        cid = channel_id(client, name)
        oldest = (datetime.now() - timedelta(days=days)).timestamp() if days else None
        found = bot_messages(client, cid, me, oldest)
    except LookupError as exc:
        print(exc)
        return 1
    except SlackApiError as exc:
        code = exc.response.get("error", str(exc))
        if code == "missing_scope":
            print(f"The app lacks a scope this needs (Slack lists: {exc.response.get('needed')}). Paste "
                  "manifest.yaml, which has the ones it uses, into your app's App Manifest, save, "
                  "and reinstall the app.")
        else:
            print(f"Slack error: {code}" + (f" ({HINTS[code]})" if code in HINTS else ""))
        return 1

    window = f" from the last {days} days" if days else ""
    print(f"{len(found)} messages by {auth.get('user')} in {name}{window}.")
    for m in found[:SHOWN]:
        print("  " + describe(m))
    if len(found) > SHOWN:
        print(f"  …and {len(found) - SHOWN} more")
    if not yes:
        print("Nothing deleted. Run again with --yes to delete them" + ("" if forget else
              " (add --forget to also clear .slack_posted.json)") + ".")
        return 0
    deleted, errors = delete(client, cid, found)
    print(f"Deleted {deleted} of {len(found)}." + (f" Failed: {', '.join(sorted(set(errors)))}." if errors else ""))
    if forget and POSTED_FILE.exists():
        POSTED_FILE.unlink()
        print("Cleared .slack_posted.json: the next pass posts everything in its window again.")
    return 1 if errors else 0

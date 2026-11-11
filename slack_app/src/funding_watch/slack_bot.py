"""Run the NIH watch from Slack: mention the bot in a channel and it runs a pass there.

    uv run funding-watch slack

The mention is the request, e.g. ``@funding-watch last 2 weeks``; code reads the
window from it (no window: the last week). Because a person asked for the pass,
it posts without the approval pause that ``funding-watch run``
has. Results go to the channel where the bot was mentioned, and the bot
answers in a thread under the mention: when it starts, then what it posted.
One pass runs at a time. ``SLACK_MODE=practice`` still composes without posting.

Socket Mode: this command opens a connection to Slack from this machine, so it
needs no public URL, but the bot only answers while the command runs, and a
mention sent while it is stopped is not picked up later. It needs
``SLACK_BOT_TOKEN`` (xoxb-…) and ``SLACK_APP_TOKEN`` (xapp-…, with the
``connections:write`` scope); README.md has the setup.
"""

from __future__ import annotations

import re
import threading
import uuid
from collections.abc import Callable

from funding_watch.config import get_settings

MENTION = re.compile(r"<@[A-Z0-9]+(?:\|[^>]*)?>")
DEFAULT_REQUEST = "New NIH funding opportunities from the last week."
HELP = ("Mention me to run a pass over what NIH posted, with a window if you like: "
        "`@funding-watch`, `@funding-watch last 2 weeks`, `@funding-watch past 10 days` (up to 8 weeks). "
        "I post a summary here, then each research group with a fit, mentioned above a table of its fits.")
BUSY = "A pass is already running. Try again when it finishes."

_running = threading.Lock()


def request_text(text: str) -> str:
    """The mention's words without anyone's name; nothing stated → the last week."""
    return MENTION.sub("", text or "").strip() or DEFAULT_REQUEST


def run_pass(request: str, channel: str, user: str) -> str:
    """Run the NIH watch for a request made in Slack, post to ``channel``, and say what happened."""
    from funding_watch import nih_watch

    config = {"configurable": {"thread_id": uuid.uuid4().hex}}
    final = nih_watch.graph.invoke({"request": request, "channel": channel, "requested_by": user}, config)
    if "__interrupt__" in final:  # not expected: a Slack request skips the approval pause
        return "The pass paused for approval, so nothing was posted."
    sent = final.get("sent")
    if not sent:
        return final.get("result") or "Nothing to post."
    head = final["result"].split("\n", 1)[0]  # "Posted 3 of 3 messages to Slack." or the practice-mode line
    errors = sorted({r["error"] for r in sent if not r["ok"]})
    return "\n".join([head, *(f"• {e}" for e in errors)])


def on_mention(event: dict, say: Callable[..., object]) -> None:
    """Slack ``app_mention`` event → one pass, answered in a thread under the mention."""
    from funding_watch.nih_watch import window_days

    thread = event.get("thread_ts") or event["ts"]
    request = request_text(event.get("text", ""))
    if request.lower() in {"help", "?"}:
        say(text=HELP, thread_ts=thread)
        return
    if not _running.acquire(blocking=False):
        say(text=BUSY, thread_ts=thread)
        return
    try:
        say(text=f"Running a pass over what NIH posted in the last {window_days(request)} days…", thread_ts=thread)
        say(text=run_pass(request, event["channel"], event.get("user", "")), thread_ts=thread)
    except Exception as exc:  # the bot keeps listening; the thread says what went wrong
        say(text=f"The pass failed: {type(exc).__name__}: {exc}", thread_ts=thread)
    finally:
        _running.release()


def build_app():
    """The Bolt app: one listener, for mentions of the bot."""
    from slack_bolt import App

    s = get_settings()
    missing = [name for name, value in (("SLACK_BOT_TOKEN", s.slack_bot_token), ("SLACK_APP_TOKEN", s.slack_app_token))
               if not value]
    if missing:
        raise RuntimeError(f"`funding-watch slack` needs {' and '.join(missing)} in .env (see README.md)")
    app = App(token=s.slack_bot_token)
    app.event("app_mention")(on_mention)
    return app


def listen() -> None:
    """Listen for mentions over Socket Mode until Ctrl-C."""
    from slack_bolt.adapter.socket_mode import SocketModeHandler

    app = build_app()
    s = get_settings()
    if s.slack_mode != "live":
        print("SLACK_MODE is not live: passes are composed but not posted (the bot still answers in threads).")
    print("Listening for mentions of the bot. Mention it in a channel it is in; Ctrl-C to stop.")
    SocketModeHandler(app, s.slack_app_token).start()

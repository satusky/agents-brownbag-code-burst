"""Command line for the NIH funding watch.

    uv run funding-watch run                          # one pass in the terminal; asks before posting
    uv run funding-watch run --request "last 2 weeks" # any window up to 8 weeks
    uv run funding-watch slack                        # run a pass whenever the bot is mentioned in Slack
    uv run funding-watch slack-cleanup [--yes]        # list (and delete) what the bot posted in the channel
    uv run funding-watch check                        # settings, model endpoint, funding source and Slack
"""

from __future__ import annotations

import argparse
import sys
import uuid


def _show(node: str, update: dict) -> None:
    """One line per finished step: the ledger note, or a routing worker's decision."""
    if node == "route":
        for r in update.get("routed", []):
            print(f"  route   {r.get('number') or r['id']}: {r.get('team') or r.get('rule')}")
        return
    notes = [e["note"] for e in (update or {}).get("ledger", [])]
    print(f"  {node:<7} {'; '.join(notes)}".rstrip())


def cmd_run(args) -> int:
    from langgraph.types import Command

    from funding_watch import nih_watch

    config = {"configurable": {"thread_id": uuid.uuid4().hex}}
    payload: object = {"request": args.request}
    print(f"NIH watch: {args.request}\n")
    while True:
        paused = None
        for chunk in nih_watch.graph.stream(payload, config, stream_mode="updates"):
            for node, update in chunk.items():
                if node == "__interrupt__":
                    paused = update[0].value
                else:
                    _show(node, update)
        if paused is None:
            print("\n" + (nih_watch.graph.get_state(config).values.get("result") or "Nothing to post."))
            return 0
        print("\n" + paused.get("preview", ""))
        try:
            answer = input(f"\n{paused['ask']} [y = post; anything else = don't post] ").strip()
        except (EOFError, KeyboardInterrupt):
            answer = ""
        payload = Command(resume=answer or "no")
        print()


def cmd_slack(args) -> int:
    from funding_watch.slack_bot import listen
    try:
        listen()
    except KeyboardInterrupt:
        return 0
    except RuntimeError as exc:
        print(exc)
        return 1
    return 0


def cmd_slack_cleanup(args) -> int:
    from funding_watch.slack_cleanup import cleanup
    return cleanup(channel=args.channel, days=args.days, yes=args.yes, forget=args.forget)


def cmd_check(args) -> int:
    from funding_watch.checks import run_checks
    return 0 if run_checks() else 1


def main(argv: list[str] | None = None) -> int:
    from funding_watch.slack_bot import DEFAULT_REQUEST  # "the last week", the same as a bare mention

    p = argparse.ArgumentParser(prog="funding-watch", description="NIH funding watch → Slack")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run one pass in the terminal, approving before anything is posted")
    r.add_argument("--request", default=DEFAULT_REQUEST, help="the window to look back over, e.g. 'last 2 weeks'")
    r.set_defaults(fn=cmd_run)
    sub.add_parser("slack", help="run a pass whenever the bot is mentioned in Slack (Socket Mode)"
                   ).set_defaults(fn=cmd_slack)
    c = sub.add_parser("slack-cleanup", help="list the bot's messages in the Slack channel; --yes deletes them")
    c.add_argument("--channel", help="channel name or ID (default: the channel in teams.json)")
    c.add_argument("--days", type=int, help="only messages from the last N days")
    c.add_argument("--yes", action="store_true", help="delete them (without it, nothing is deleted)")
    c.add_argument("--forget", action="store_true", help="with --yes, also clear .slack_posted.json")
    c.set_defaults(fn=cmd_slack_cleanup)
    sub.add_parser("check", help="check settings, the model endpoint and Slack").set_defaults(fn=cmd_check)
    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())

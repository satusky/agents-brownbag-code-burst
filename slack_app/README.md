# NIH funding watch → Slack

A LangGraph workflow that reads what NIH posted on Grants.gov, drops what a
research institute would not apply for (fixed rules in code), asks the model
which research group, if any, each remaining opportunity fits, and posts the
fits to a Slack channel, mentioning each group above a table of its fits. A
person approves before anything is posted, unless they asked for the pass by
mentioning the bot in Slack.

This folder is its own project, separate from the rest of the repo. It was
copied from the NIH watch stage of the custom agents seminar.

## Quick start

```bash
cd slack_app
cp .env.example .env        # fill in the model endpoint; Slack settings are below
uv sync
uv run funding-watch check  # settings, model endpoint, funding source and Slack
uv run funding-watch run    # one pass over the last week; asks before posting
```

| Command | What it does |
|---|---|
| `uv run funding-watch run [--request "last 2 weeks"]` | one pass in the terminal, any window up to 8 weeks; approve before posting |
| `uv run funding-watch slack` | runs a pass whenever the bot is mentioned in Slack |
| `uv run funding-watch slack-cleanup [--yes]` | lists (and with `--yes`, deletes) what the bot posted |
| `uv run funding-watch check` | checks settings, the model endpoint and Slack |

## Layout

```
src/funding_watch/
  nih_watch.py       the graph: fetch → screen → route (one worker per opportunity) → compose → approve → post
  slack.py           posting: practice (nothing sent) or live, plus teams.json and .slack_posted.json
  slack_bot.py       `funding-watch slack`: a pass per mention, over Socket Mode
  slack_cleanup.py   `funding-watch slack-cleanup`
  cli.py             the `funding-watch` command
  funding/           Grants.gov, NIH and NSF clients, records, date math
  config.py          settings from .env (see .env.example)
  models.py          get_model()
  approval.py        the approval pause (LangGraph interrupt)
  checkpoint.py      the checkpointer the approval pause needs
  checks.py          `funding-watch check`
manifest.yaml        creates the Slack app
teams.json           the channel, and who to mention for each research group
data/                research group profiles, and fictional fixture records (FUNDING_SOURCE=fixtures)
```

## Slack setup

The watch runs in **practice** mode until you switch it: messages are composed
and shown, but nothing is sent. Everything goes to one channel: a summary of
the run, then for each research group with a fit, its mention above one table
of its fits, with a Fit column (strong or possible, strong first). Slack
allows one table per message, so each group's table is its own message.
To post for real:

1. **Create the app.** At <https://api.slack.com/apps>, choose *Create New App →
   From a manifest*, pick the workspace, and paste `manifest.yaml`. Then
   *Install to Workspace*. The app can only post (`chat:write`).
2. **Copy the token.** *OAuth & Permissions → Bot User OAuth Token* (`xoxb-…`).
   Put it in `.env`, never in code:

   ```bash
   SLACK_MODE=live
   SLACK_BOT_TOKEN=xoxb-...
   ```

3. **Name the channel and the teams.** Edit `teams.json`: `channel` is where
   every message goes, and `teams` says who to mention for each research group.
   A mention notifies people only when it is a Slack ID:
   - a member ID (`U…`): open the person's profile, *⋮ → Copy member ID*;
   - a list of member IDs, to mention several people;
   - a user group ID (`S…`), to mention a group handle. User groups need a
     paid Slack plan.

   Anything else, like the `@analytics-team` placeholders, is shown as written
   and notifies no one. Set `digest` to `false` to skip the run summary.
4. **Invite the app** to the channel: `/invite @funding-watch`.
5. **Check:** `uv run funding-watch check` shows the bot and workspace and how many
   teams have Slack IDs, and `uv run funding-watch run` posts after you approve.

Live runs record what they posted in `.slack_posted.json` (git-ignored), so the
next run skips those opportunities. Delete the file to post them again.

### Run a pass by mentioning the bot

`uv run funding-watch slack` listens for mentions of the bot. Mention it in a channel
it has been invited to, and it runs a pass and posts the results in that
channel without asking for approval, since asking for the pass is the approval:

```text
@funding-watch                  the last week
@funding-watch last 2 weeks     any window up to 8 weeks
@funding-watch help             what it can do
```

It answers in a thread under your message: when it starts, then what it posted
(or what went wrong). One pass runs at a time.

It uses Socket Mode: the command connects to Slack from your machine, so there
is no public URL to set up, but the bot only answers while the command runs.
Mentions sent while it is stopped are not picked up later.

Setup, once:

1. **Update the app.** If you created it from an older `manifest.yaml`: your
   app → *App Manifest* → paste the current `manifest.yaml` → *Save*. It adds
   the `app_mentions:read` scope, the `app_mention` event and Socket Mode.
   Then *Install App → Reinstall to Workspace*. If the Bot User OAuth Token
   changes, update `SLACK_BOT_TOKEN` in `.env`.
2. **Create an app-level token.** *Basic Information → App-Level Tokens →
   Generate Token and Scopes*, add the `connections:write` scope, and copy the
   token (`xapp-…`) into `.env`:

   ```bash
   SLACK_APP_TOKEN=xapp-...
   ```

3. **Start it:** `uv run funding-watch slack`, then mention the bot.

### Delete what the bot posted

When you are done testing:

```bash
uv run funding-watch slack-cleanup                  # lists the bot's messages in the channel; deletes nothing
uv run funding-watch slack-cleanup --yes            # deletes them
uv run funding-watch slack-cleanup --yes --forget   # and clears .slack_posted.json, so passes post again
```

It finds the bot's posts and its replies in threads, in the channel from
`teams.json` (or `--channel`), optionally only the last `--days N`. A bot can
only delete its own messages, so your mentions stay; delete those yourself. It
needs the `channels:history`, `groups:history`, `channels:read` and
`groups:read` scopes from the current `manifest.yaml` (update the manifest and
reinstall, as above).

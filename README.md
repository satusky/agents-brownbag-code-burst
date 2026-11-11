# Custom agents: code burst examples

Starting points for the code burst that follows the custom agents brown bag. Each
example is small, works as it is, and is meant to be copied and changed. Pick the
one closest to what you want to build:

| Example | What it is | Start with |
|---|---|---|
| [Snippets](#snippets) | one file per LangGraph pattern: chaining, routing, parallel nodes, evaluator loops, human approval, agents, orchestrator-worker, subgraphs | `snippets/` |
| [Coding agent](#the-coding-agent) | the classic tool-calling loop: a model, four file tools, and a `ToolNode` | `src/agents_brownbag_code_burst/coding_agent.py` |
| [Slack app](#the-slack-app) | a complete app: a LangGraph workflow that routes new NIH funding opportunities to research groups and posts them to Slack, or runs when someone mentions the bot | `slack_app/` |

All of them use LangGraph with any OpenAI-compatible model endpoint (Azure OpenAI by
default). [Resources](#resources) at the end links the LangGraph and LangChain docs,
the LangChain agent skills for coding agents, and Slack's developer docs.

## Setup

You need Python 3.11+, [uv](https://docs.astral.sh/uv/getting-started/installation/),
and a model endpoint: a URL, an API key and a model name.

```bash
git clone https://github.com/satusky/agents-brownbag-code-burst.git
cd agents-brownbag-code-burst
cp .env.example .env   # the model endpoint: URL, key, model name
uv sync
uv run pytest          # offline, no model calls
```

The Slack app is a separate project with its own `.env` and `uv sync`; see
[The Slack app](#the-slack-app).

## Building on the examples

- **A new workflow:** copy the snippet closest to your idea, then change its state,
  prompts and nodes. Each snippet stands alone.
- **Another model:** `get_model()` in `models.py` reads the endpoint from `.env`;
  anything OpenAI-compatible works.
- **New tools for the coding agent:** write a `@tool` function in `coding_tools.py`
  and add it to `CODING_TOOLS`.
- **The Slack app on your own data:** replace `fetch` in `nih_watch.py`, the groups in
  `data/research_profiles/renci_groups.json` and the `ROUTE` prompt. Composing,
  approval, posting and the bot stay the same.
- **A new bot command:** `on_mention` in `slack_bot.py` gets the text of every
  mention; answer a keyword the way it answers `help`.

## Snippets

Each file stands alone and shows only the LangGraph mechanics. Lines are at most
88 characters.

```bash
uv run python snippets/01_prompt_chain.py    # uses the model endpoint in .env
```

| File | Pattern | The lines to point at | Docs |
|---|---|---|---|
| `01_prompt_chain.py` | Prompt chaining | `add_edge("extract", "write_brief")` | [prompt chaining](https://docs.langchain.com/oss/python/langgraph/workflows-agents#prompt-chaining) |
| `02_routing.py` | Routing | `with_structured_output(Route)`, `add_conditional_edges("route", pick_group, ...)` | [routing](https://docs.langchain.com/oss/python/langgraph/workflows-agents#routing) |
| `03_parallel.py` | Parallelization | two `add_edge(START, ...)`, `add_edge([...], "recommend")` | [parallelization](https://docs.langchain.com/oss/python/langgraph/workflows-agents#parallelization) |
| `04_evaluator_optimizer.py` | Evaluator-optimizer | `next_step` (code stops the loop), `add_conditional_edges("evaluate", ...)` | [evaluator-optimizer](https://docs.langchain.com/oss/python/langgraph/workflows-agents#evaluator-optimizer) |
| `04b_human_in_the_loop.py` | Evaluator-optimizer with a person | `interrupt(...)`, `checkpointer=InMemorySaver()`, `Command(resume=...)` | [interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts) |
| `05_agent.py` | Agent | `@tool`, `bind_tools`, `ToolNode`, `tools_condition` | [agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents#agents) |
| `06_orchestrator_worker.py` | Orchestrator-worker | `Annotated[list, operator.add]`, `Send("worker", ...)` | [orchestrator-worker](https://docs.langchain.com/oss/python/langgraph/workflows-agents#orchestrator-worker) |
| `07_subgraphs.py` | Subgraphs + supervisor | `add_node("discover", discover)` (a compiled graph), `supervisor` | [subgraphs](https://docs.langchain.com/oss/python/langgraph/use-subgraphs) |
| `08_custom_workflow.py` | Deterministic workflow | `screen`/`score`/`report` are code; `needs_judge` decides whether the model runs | [conditional edges](https://docs.langchain.com/oss/python/langgraph/graph-api#conditional-edges) |
| `09_nih_watch.py` | `Send` workers + approval | `Send("route", ...)`, then `interrupt(...)` before `post` | [`Send`](https://docs.langchain.com/oss/python/langgraph/graph-api#send), [approve or reject](https://docs.langchain.com/oss/python/langgraph/interrupts#approve-or-reject) |

`04b` and `09` pause and ask for an answer in the terminal. `09` is the cut-down
version of the [Slack app](#the-slack-app).

## The coding agent

`src/agents_brownbag_code_burst/coding_agent.py` is the classic loop: a model bound to four
tools, and a `ToolNode`, until the model stops calling tools. The tools are in
`coding_tools.py`: `read_file`, `edit_file`, `write_file`, and a `bash` that runs
only `ls`, `grep` and `python example.py`. Each run works in its own copy of
`examples/coding_agent/`, whose `example.py` fails; the template is never changed.

```bash
uv run python -m agents_brownbag_code_burst.coding_agent                       # "example.py fails. Find the bug and fix it."
uv run python -m agents_brownbag_code_burst.coding_agent "Add a days_left column to the report"
```

To point it at another folder, put `project_dir` in the run's config
(`{"configurable": {"project_dir": "..."}}`); the tools then work there instead of
on a copy.

## The Slack app

`slack_app/` is the NIH funding watch, a full LangGraph workflow behind a Slack bot:

1. **fetch** (code): what NIH posted on Grants.gov in the last week, or any window up
   to 8 weeks.
2. **screen** (code): fixed rules drop training awards, required clinical trials,
   limited competitions, deadlines that are too close, and anything already posted.
3. **route** (model, one `Send` worker per opportunity, in parallel): which research
   group should see it, and whether the fit is strong or possible. Code checks that
   the model's evidence is really in the announcement.
4. **compose** (code): a summary, then for each group, a mention above a table of its
   fits.
5. **approve** (a person, `interrupt()`), then **post** (code). A pass someone asks
   for by mentioning the bot skips the pause: the mention is the approval.

It is its own uv project. [`slack_app/README.md`](slack_app/README.md) has the
layout and more detail on each step below.

### Try it without Slack

The app starts in **practice** mode: messages are composed and shown, and nothing is
sent.

```bash
cd slack_app
cp .env.example .env         # fill in the model endpoint; the comments say what each command needs
uv sync
uv run funding-watch run     # one pass over the last week; shows the messages, asks before "posting"
```

### Create the app in Slack

You need a Slack workspace where you can install apps. If your workspace requires
approval for new apps, an admin has to approve the install.

1. **Name your bot (optional).** If others at the code burst are creating apps in
   the same workspace, change `display_information.name` and
   `features.bot_user.display_name` in `slack_app/manifest.yaml` so each bot is
   easy to tell apart. The steps below use the default name, `funding-watch`.
2. **Create the app from the manifest.** At <https://api.slack.com/apps>, choose
   **Create New App → From a manifest**, pick the workspace, paste
   `slack_app/manifest.yaml`, and create it. The manifest asks for the scopes the
   app needs (post messages, hear mentions, and read the channel's history for
   cleanup) and turns on Socket Mode, so no public URL is needed.
3. **Install it.** **Install App → Install to Workspace**, then allow it.
4. **Copy the bot token.** **OAuth & Permissions → Bot User OAuth Token**
   (`xoxb-…`) goes in `slack_app/.env` as `SLACK_BOT_TOKEN`.
5. **Create an app-level token.** **Basic Information → App-Level Tokens → Generate
   Token and Scopes**, add the `connections:write` scope, and put the token
   (`xapp-…`) in `slack_app/.env` as `SLACK_APP_TOKEN`. Only the bot listener
   needs it.
6. **Switch to live.** In `slack_app/.env`, set `SLACK_MODE=live`.
7. **Choose the channel and who to mention.** In `slack_app/teams.json`, `channel`
   is where every message goes, and `teams` maps each research group to who gets
   mentioned. A mention notifies people only when it is a Slack ID: a member ID
   (`U…`; open a profile, **⋮ → Copy member ID**), a list of member IDs, or a user
   group ID (`S…`, paid plans only). The `@analytics-team` placeholders are shown
   as written and notify no one.
8. **Invite the bot to the channel.** In the channel, type `/invite @funding-watch`.
9. **Check the setup.** `uv run funding-watch check` reports the settings, the model
   endpoint, the bot and workspace, and how many teams have Slack IDs.

### Run it in Slack

Either run a pass from the terminal, which asks before it posts:

```bash
uv run funding-watch run --request "last 2 weeks"
```

or start the bot and ask for a pass in Slack:

```bash
uv run funding-watch slack   # listens until Ctrl-C
```

```text
@funding-watch                  a pass over the last week
@funding-watch last 2 weeks     any window up to 8 weeks
@funding-watch help             what it can do
```

The bot answers in a thread under your mention, posts the results in that channel,
and runs one pass at a time. It hears mentions only while `funding-watch slack` is
running; mentions sent while it is stopped are not picked up later.

Live runs record what they posted in `slack_app/.slack_posted.json` (git-ignored), so
later passes skip those opportunities. When you are done testing:

```bash
uv run funding-watch slack-cleanup                  # lists the bot's messages; deletes nothing
uv run funding-watch slack-cleanup --yes            # deletes them
uv run funding-watch slack-cleanup --yes --forget   # and clears .slack_posted.json
```

## Resources

### LangGraph and LangChain docs

- [LangGraph overview](https://docs.langchain.com/oss/python/langgraph/overview)
- [Workflows and agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents): the patterns the snippets follow
- [Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api): state, reducers, nodes, edges, `Send` and `Command`
- [Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts): pausing for a person
- [Persistence](https://docs.langchain.com/oss/python/langgraph/persistence): checkpointers and threads
- [Streaming](https://docs.langchain.com/oss/python/langgraph/streaming)
- [Subgraphs](https://docs.langchain.com/oss/python/langgraph/use-subgraphs)
- [LangChain overview](https://docs.langchain.com/oss/python/langchain/overview), [tools](https://docs.langchain.com/oss/python/langchain/tools) and [structured output](https://docs.langchain.com/oss/python/langchain/structured-output)
- [Azure OpenAI chat models](https://docs.langchain.com/oss/python/integrations/chat/azure_chat_openai)
- [LangGraph API reference](https://reference.langchain.com/python/langgraph/overview)

### Agent skills and docs for your coding agent

[LangChain Skills](https://github.com/langchain-ai/langchain-skills) are agent skills
(`SKILL.md` files) that teach coding agents such as Claude Code, Cursor and Codex
how to build with LangGraph, LangChain and Deep Agents. Examples include
`langgraph-fundamentals`, `langgraph-human-in-the-loop`, `langgraph-persistence` and
`langchain-fundamentals`. The project is in early development.

```bash
npx skills add langchain-ai/langchain-skills --skill '*' --yes   # this project, any agent
```

In Claude Code, you can install them as a plugin instead:

```text
/plugin marketplace add langchain-ai/langchain-skills
/plugin install langchain-skills@langchain-skills
```

The docs themselves are also available to coding agents
([Use these docs](https://docs.langchain.com/use-these-docs)): an MCP server for the
guides and one for the API reference, plus
[llms.txt](https://docs.langchain.com/llms.txt). In Claude Code:

```bash
claude mcp add --transport http docs-langchain https://docs.langchain.com/mcp
claude mcp add --transport http reference-langchain https://reference.langchain.com/mcp
```

[LangSmith Skills](https://github.com/langchain-ai/langsmith-skills) cover tracing
and datasets.

### Slack

- [Your apps](https://api.slack.com/apps): create, configure and install apps
- [App manifests](https://docs.slack.dev/app-manifests/configuring-apps-with-app-manifests)
- [Tokens](https://docs.slack.dev/authentication/tokens): bot (`xoxb-`) and app-level (`xapp-`) tokens
- [Bolt for Python](https://docs.slack.dev/tools/bolt-python/) and its [Socket Mode guide](https://docs.slack.dev/tools/bolt-python/concepts/socket-mode)
- [Using Socket Mode](https://docs.slack.dev/apis/events-api/using-socket-mode/)
- [`chat.postMessage`](https://docs.slack.dev/reference/methods/chat.postMessage) and the [`app_mention` event](https://docs.slack.dev/reference/events/app_mention)
- [Block Kit](https://docs.slack.dev/block-kit/), the [table block](https://docs.slack.dev/reference/block-kit/blocks/table-block), and the [Block Kit Builder](https://app.slack.com/block-kit-builder) for trying out messages

## Layout

```
snippets/                  01–09, one pattern each
src/agents_brownbag_code_burst/
  config.py                settings from .env (see .env.example)
  models.py                get_model(), shared by everything
  coding_agent.py          the coding agent
  coding_tools.py          its four tools
examples/coding_agent/     the project the coding agent fixes (copied per run)
tests/                     offline tests
slack_app/                 the NIH funding watch Slack app (its own uv project)
  src/funding_watch/       the graph (nih_watch.py), the bot, posting, and the funding data clients
  manifest.yaml            creates the Slack app
  teams.json               the channel, and who to mention for each research group
  .env.example             the settings each command needs
```

# Brown bag demos

The demos for the custom agents brown bag:

- `snippets/`: the smallest version of each LangGraph workflow pattern, for slides.
- `server/`: runs every snippet as a chat in the llm-demos chat UI.
- the coding agent: `src/brown_bag_demos/coding_agent.py`, its tools, and the small
  project it works on.

The full seminar stages these snippets are cut down from are in
`~/Desktop/custom-agents-brownbag/src/custom_agents_brownbag/seminar/`.

## Setup

The chat UI comes from `~/Desktop/llm-demos`, a path dependency, so that folder must
sit next to this one.

```bash
cp .env.example .env   # the model endpoint: URL, key, model name
uv sync
uv run pytest          # offline, no model calls
```

## Snippets

Each file stands alone and shows only the LangGraph mechanics. The rules the full
stages add (date checks, citations, caps, real funding data) are left out. Lines are
at most 88 characters.

```bash
uv run python snippets/01_prompt_chain.py    # uses the model endpoint in .env
```

| File | Pattern | The lines to point at | Full stage |
|---|---|---|---|
| `01_prompt_chain.py` | Prompt chaining | `add_edge("extract", "write_brief")` | `chain.py` |
| `02_routing.py` | Routing | `with_structured_output(Route)`, `add_conditional_edges("route", pick_group, ...)` | `router.py` |
| `03_parallel.py` | Parallelization | two `add_edge(START, ...)`, `add_edge([...], "recommend")` | `parallel.py` |
| `04_evaluator_optimizer.py` | Evaluator-optimizer | `next_step` (code stops the loop), `add_conditional_edges("evaluate", ...)` | `evaluator.py` |
| `04b_human_in_the_loop.py` | Evaluator-optimizer with a person | `interrupt(...)`, `checkpointer=InMemorySaver()`, `Command(resume=...)` | `evaluator_human.py` |
| `05_agent.py` | Agent | `@tool`, `bind_tools`, `ToolNode`, `tools_condition` | `agent.py` |
| `06_orchestrator_worker.py` | Orchestrator-worker | `Annotated[list, operator.add]`, `Send("worker", ...)` | `orchestrator.py` |
| `07_subgraphs.py` | Subgraphs + supervisor | `add_node("discover", discover)` (a compiled graph), `supervisor` | `assistant.py` |
| `08_custom_workflow.py` | Deterministic workflow | `screen`/`score`/`report` are code; `needs_judge` decides whether the model runs | `workflow.py` |
| `09_nih_watch.py` | `Send` workers + approval | `Send("route", ...)`, then `interrupt(...)` before `post` | `nih_watch.py` |
| `10_ui_agent.py` | Agent (a chat UI demo, not a slide) | the coding agent's tools, working on the chat page's stylesheets | `agent.py` |

`04b` and `09` pause and ask for an answer in the terminal.

## The chat UI

`server/serve.py` runs every snippet in the llm-demos chat UI, one chat per snippet.

```bash
uv run python server/serve.py --open   # http://127.0.0.1:8000/
```

`/` lists the snippets and `/05/` is the agent. Send your own input, or **example**
for the snippet's sample. The bubbles show the graph as it runs:

| Bubble | What it is |
|---|---|
| System · `node` | a system prompt that node sent to a model, shown once per chat |
| Reasoning · `node` | a summary of a model's reasoning in that node; `--reasoning off` turns it off |
| Assistant · `node` | text a model wrote inside that node; parallel nodes and `Send` workers stream side by side |
| Tool call · `name` | a tool call, or a structured output (`Route`, `Grade`, `Plan`) |
| Tool result · `name` | what a tool returned (05, 10) |
| Assistant · result | an output made by code: a table, a count, what was posted |

When a graph pauses at `interrupt()` (04b, 09), your next message is the answer.
"New chat" starts over. Steps that are only code (screen, score, supervisor) make no
bubble.

`/10/` is the coding agent working on the page itself: ask it to change the font or
the colors and the page changes while it answers. Its project folder is a copy of
the chat's stylesheets (the server prints where), served ahead of llm-demos' own
files; llm-demos' hot reload swaps each saved `.css` file into the open page. Every
server start makes a fresh copy, so a restart undoes the agent's changes, and the
files in `~/Desktop/llm-demos` are never edited. Other open chats show the change
when reloaded.

To add a snippet to the server, give it an entry in `SPECS` in `server/serve.py`:
what to ask for, a sample input, and how a message becomes the graph's input.

## The coding agent

`src/brown_bag_demos/coding_agent.py` is the classic loop: a model bound to four
tools, and a `ToolNode`, until the model stops calling tools. The tools are in
`coding_tools.py`: `read_file`, `edit_file`, `write_file`, and a `bash` that runs
only `ls`, `grep` and `python example.py`. Each run works in its own copy of
`examples/coding_agent/`, whose `example.py` fails; the template is never changed.

```bash
uv run python -m brown_bag_demos.coding_agent                       # "example.py fails. Find the bug and fix it."
uv run python -m brown_bag_demos.coding_agent "Add a days_left column to the report"
```

`snippets/10_ui_agent.py` is the same loop and tools with its own system prompt and
a `project_dir` in the run's config, so it works on the chat page instead.

## Layout

```
snippets/                  01–10, one pattern each
server/serve.py            the chat server; server/ui/index.html is its chat page
src/brown_bag_demos/
  config.py                settings from .env (see .env.example)
  models.py                get_model(), shared by everything
  coding_agent.py          the coding agent
  coding_tools.py          its four tools
examples/coding_agent/     the project the coding agent fixes (copied per run)
tests/                     offline tests
```

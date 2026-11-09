"""Serve the snippets in the llm-demos chat UI (~/Desktop/llm-demos).

One server, one chat per snippet: http://127.0.0.1:8000/ lists them and
http://127.0.0.1:8000/05/ is the agent. A message runs the snippet's graph on
what you typed, or on its sample input if you send "example". The bubbles show
what the graph does while it runs:

  System · <node>        a system prompt that node sent to a model (once per chat)
  Reasoning · <node>     a summary of a model's reasoning in that node (--reasoning off hides it)
  Assistant · <node>     text a model wrote inside that node (parallel nodes stream side by side)
  Tool call · <name>     a tool call, or a structured output (Route, Grade, Plan, Answer)
  Tool result · <name>   what a tool returned
  Assistant · result     an output made by code (a table, a count, what was posted)

When a graph pauses at interrupt() (04b, 09), your next message is the answer.

10 is the coding agent working on this page. Its project folder is a copy of the
chat's stylesheets, served ahead of llm-demos' own, and every .css file it saves is
swapped into the open page. Each server start makes a fresh copy, so a restart
undoes its changes.

Run from the project root (llm-demos is a path dependency on ../llm-demos):

  uv run python server/serve.py --open
"""

from __future__ import annotations

import argparse
import contextlib
import html
import importlib.util
import json
import os
import re
import shutil
import sys
import tempfile
import webbrowser
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType
from typing import Any

try:
    from llm_demos.core.demo import Demo
    from llm_demos.core.events import (
        Message,
        MessageDelta,
        MessageEnd,
        MessageEvent,
        MessageStart,
        MessageType,
        new_id,
        whole_message,
    )
    from llm_demos.core.langchain_stream import to_langchain
    from llm_demos.core.server import WEB_DIR, create_app
except ImportError:
    raise SystemExit(
        "llm-demos is not installed in this environment. It is a path dependency on\n"
        "../llm-demos (see pyproject.toml); from the project root, run:\n"
        "  uv run python server/serve.py"
    ) from None

from collections import defaultdict, deque

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, SystemMessage, ToolMessage
from langgraph.types import Command

HERE = Path(__file__).resolve().parent
PAGE_DIR = HERE / "ui"  # the chat page, served at /<id>/
SNIPPETS_DIR = HERE.parent / "snippets"  # one chat per snippet with an entry in SPECS


# ----------------------------------------------------------------- what each snippet takes and shows
@dataclass
class Spec:
    ask: str  # what to send, shown in the greeting
    example: str  # used when the message is "example"
    make_input: Callable[[str], dict] | None  # message → graph input; None: the chat so far (the agent)
    result: Callable[[dict], str] | None = None  # an output made by code, shown when the run ends
    pause: Callable[[Any], str] | None = None  # what to say when the graph pauses at interrupt()
    answer: Callable[[str], Any] = str.strip  # the reply to a pause → Command(resume=...)
    edits_page: bool = False  # a coding agent whose project folder is this page's stylesheets
    title: str | None = None  # instead of "<id> · <pattern>" from the docstring
    greeting: bool = True  # open the chat with a message saying what to send


ANNOUNCEMENT = (
    "DEMO-101 Climate Data Cyberinfrastructure. Funds shared platforms and computing services "
    "for climate research. Universities may apply. "
    "Letter of intent due 2026-12-01; full proposal due 2027-02-15."
)
PROFILE = "RENCI, a research institute at UNC-Chapel Hill: data science, computing."
OPPORTUNITIES = """\
2027-02-15 Climate data platforms
2027-03-01 Network research testbeds
2026-10-01 Research software sustainability
2027-01-10 Pediatric clinical trial planning
2027-04-30 Digital twins of coastal ecosystems"""


def opportunities(text: str) -> dict:
    rows = re.findall(r"^\s*(\d{4}-\d{2}-\d{2})\s+(.+?)\s*$", text, re.M)
    if not rows:
        raise ValueError("Write one opportunity per line, as: 2027-02-15 Climate data platforms")
    return {"opportunities": [{"deadline": day, "title": title} for day, title in rows]}


def bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items) or "_(none)_"


def tries(state: dict) -> str:
    n = state["tries"]
    verdict = "Passed" if state["passed"] else "Did not pass"
    return f"{verdict} after {n} {'try' if n == 1 else 'tries'}. Code stops the loop at 3."


SPECS = {
    "01": Spec("Paste a funding announcement", ANNOUNCEMENT, lambda t: {"announcement": t}),
    "02": Spec("Describe a funding opportunity",
               "Network research testbeds: programmable 100G links between campuses.",
               lambda t: {"opportunity": t}),
    "03": Spec("Describe a funding opportunity",
               "Climate data platforms. Universities may apply. Due 2027-02-15.",
               lambda t: {"opportunity": t, "profile": PROFILE}),
    "04": Spec("Paste a funding announcement", ANNOUNCEMENT, lambda t: {"announcement": t},
               result=tries),
    "04b": Spec("Paste a funding announcement", ANNOUNCEMENT, lambda t: {"announcement": t},
                pause=lambda draft: "Paused at `review`. Type **approve**, or say what to fix.",
                result=lambda state: "Approved."),
    "05": Spec("Ask a question",
               "Find a climate data opportunity. How many days until it is due?", None),
    "06": Spec("Describe an organization's research groups",
               "RENCI has three research groups: Earth Data Science, Networking Research, "
               "and Software Architecture.",
               lambda t: {"profile": t},
               result=lambda state: bullets(state["summary"].splitlines())),
    "07": Spec("Name a research group to find grants for", "a research data management group",
               lambda t: {"request": t}),
    "08": Spec("List opportunities, one per line as `YYYY-MM-DD title`", OPPORTUNITIES, opportunities,
               result=lambda state: f"```text\n{state['result']}\n```" if state["result"]
               else "No opportunity fits."),
    "09": Spec("Send anything to check the snippet's sample NIH postings", "", lambda t: {},
               pause=lambda messages: f"Post these?\n\n{bullets(messages)}\n\nType **yes** or **no**.",
               answer=lambda t: t.strip().lower(),
               result=lambda state: f"Posted:\n\n{bullets(state['messages'])}" if state["approved"]
               else "Nothing posted."),
    "10": Spec("Ask the agent to change how this page looks",
               "Change the font of this page to Comic Sans.", None, edits_page=True,
               title="Coding agent", greeting=False),
}


# ----------------------------------------------------------------- LangGraph stream → chat bubbles
def task_of(meta: dict) -> str:
    """The task a model call runs in: unique per parallel branch, Send worker and subgraph node."""
    return meta.get("langgraph_checkpoint_ns") or meta.get("langgraph_node") or ""


class SystemPrompts(BaseCallbackHandler):
    """Record the system messages each model call is sent, by task.

    LangGraph's ``messages`` stream carries what models write, not what they are
    sent. This callback sees each call start (before its first chunk) and keeps
    its system prompts until Bubbles shows them. Nodes run in worker threads;
    deque appends and pops are thread-safe.
    """

    run_inline = True  # record before the call starts, also for async nodes

    def __init__(self) -> None:
        self.waiting: defaultdict[str, deque[list[str]]] = defaultdict(deque)  # task → one list per call

    def on_chat_model_start(self, serialized, messages, *, metadata=None, **kwargs) -> None:
        sent = [m.text for batch in messages for m in batch if isinstance(m, SystemMessage)]
        self.waiting[task_of(metadata or {})].append(sent)

    def take(self, task: str) -> list[str]:
        calls = self.waiting.get(task)
        return calls.popleft() if calls else []


class Bubbles:
    """Turn LangGraph's ``messages`` stream into the chat's bubble events.

    Parallel branches and Send workers stream at the same time, so every task
    (its checkpoint namespace) keeps its own open bubbles. A model call's last
    chunk closes them. Text and tool calls from one model call share a group,
    so the chat history can be turned back into LangChain messages (the agent).
    A call's system prompt comes first, once per chat for each node and prompt.
    """

    def __init__(self, prompts: SystemPrompts, shown: set[tuple[str | None, str]]) -> None:
        self.calls: dict[str, dict] = {}  # task → {"group", "bubbles": {part: bubble id}, "ended": {id}}
        self.prompts, self.shown = prompts, shown  # shown: (node, system prompt) already in the chat

    def add(self, msg: BaseMessage, meta: dict) -> list[MessageEvent]:
        if isinstance(msg, ToolMessage):
            return whole_message(MessageType.TOOL_RESULT, msg.text, name=msg.name,
                                 tool_call_id=msg.tool_call_id, group=msg.id)
        if not isinstance(msg, AIMessage):
            return []
        node, task = meta.get("langgraph_node"), task_of(meta)
        events: list[MessageEvent] = []
        if task not in self.calls:  # a model call's first chunk: first, what it was told
            for text in self.prompts.take(task):
                if (node, text) not in self.shown:
                    self.shown.add((node, text))
                    events += whole_message(MessageType.SYSTEM, text, name=node)
            self.calls[task] = {"group": new_id(), "bubbles": {}, "ended": set()}
        model_call = self.calls[task]

        def write(part, text: str, **fields) -> None:
            bubbles = model_call["bubbles"]
            if part not in bubbles:
                if bubbles:  # a call streams its parts in turn (reasoning, then text or tool calls)
                    events.extend(self.end(model_call, *list(bubbles.values())[-1:]))
                start = MessageStart(group=model_call["group"], **fields)
                bubbles[part] = start.id
                events.append(start)
            if text:
                events.append(MessageDelta(id=bubbles[part], delta=text))

        for block in msg.content_blocks:
            if block["type"] == "text" and block.get("text"):
                write("text", block["text"], type=MessageType.ASSISTANT, name=node)
            elif block["type"] == "reasoning" and block.get("reasoning"):
                write("reasoning", block["reasoning"], type=MessageType.REASONING, name=node)
        if isinstance(msg, AIMessageChunk):
            for call in msg.tool_call_chunks:
                index = call["id"] if call.get("index") is None else call["index"]
                write(("tool", index), call.get("args") or "", type=MessageType.TOOL_CALL,
                      name=call.get("name"), tool_call_id=call.get("id"))
        else:  # a whole message, from a model that did not stream
            for call in msg.tool_calls:
                write(("tool", call["id"]), json.dumps(call["args"]), type=MessageType.TOOL_CALL,
                      name=call["name"], tool_call_id=call["id"])

        if not isinstance(msg, AIMessageChunk) or msg.chunk_position == "last":
            events += self.close(task)
        return events

    @staticmethod
    def end(model_call: dict, *bubbles: str) -> list[MessageEvent]:
        fresh = [b for b in bubbles if b not in model_call["ended"]]
        model_call["ended"].update(fresh)
        return [MessageEnd(id=b) for b in fresh]

    def close(self, *tasks: str) -> list[MessageEvent]:
        events: list[MessageEvent] = []
        for task in tasks or list(self.calls):
            if model_call := self.calls.pop(task, None):
                events += self.end(model_call, *model_call["bubbles"].values())
        return events


def reply(text: str, name: str) -> list[MessageEvent]:
    return whole_message(MessageType.ASSISTANT, text, name=name, group=new_id())


# ----------------------------------------------------------------- one snippet = one chat
@dataclass
class Snippet:
    id: str
    module: ModuleType
    spec: Spec
    paused: dict[str, str] = field(default_factory=dict)  # conversation → thread waiting at interrupt()
    configurable: dict = field(default_factory=dict)  # added to every run's config (project_dir)

    def __post_init__(self) -> None:
        lines = (self.module.__doc__ or "").strip().splitlines()
        pattern, _, tagline = lines[0].partition(":")
        self.title = self.spec.title or f"{self.id} · {pattern}"
        self.diagram = lines[2].strip() if len(lines) > 2 else ""
        text = [f"**{self.title}.**{tagline}", f"`{self.diagram}`"]
        if self.spec.example:
            text += [f"{self.spec.ask}, or send **example** to use:", f"```text\n{self.spec.example}\n```"]
        else:
            text.append(f"{self.spec.ask}.")
        self.greeting = (Message(type=MessageType.ASSISTANT, content="\n\n".join(text), done=True)
                         if self.spec.greeting else None)

    def expand(self, text: str) -> str:
        return self.spec.example if self.spec.example and text.strip().lower() == "example" else text

    def make_input(self, history: list[Message]) -> dict:
        if self.spec.make_input is None:  # the agent: the whole conversation, as LangChain messages
            # System bubbles only show what nodes sent; the agent node adds its own system prompt.
            chat = [m.model_copy(update={"content": self.expand(m.content)}) if m.type == MessageType.USER
                    else m for m in history
                    if m.type != MessageType.SYSTEM and not (self.greeting and m.id == self.greeting.id)]
            return {"messages": to_langchain(chat)}
        last = next(m for m in reversed(history) if m.type == MessageType.USER)
        return self.spec.make_input(self.expand(last.content))

    async def respond(self, history: list[Message]) -> AsyncIterator[MessageEvent]:
        graph, spec = self.module.graph, self.spec
        users = [m for m in history if m.type == MessageType.USER]
        conversation = users[0].id  # "New chat" starts a new conversation
        if conversation in self.paused:  # this message answers the interrupt
            thread = self.paused.pop(conversation)
            graph_input = Command(resume=spec.answer(users[-1].content))
        else:  # a new run on a new thread, so no state from an earlier run leaks in
            thread = users[-1].id
            try:
                graph_input = self.make_input(history)
            except ValueError as exc:  # input the snippet can't use: say so in the chat
                for event in reply(str(exc), "input"):
                    yield event
                return
        prompts = SystemPrompts()
        config = {"configurable": {"thread_id": thread, **self.configurable}, "callbacks": [prompts]}
        shown = {(m.name, m.content) for m in history if m.type == MessageType.SYSTEM}

        bubbles, state = Bubbles(prompts, shown), {}
        async for namespace, mode, data in graph.astream(
            graph_input, config, stream_mode=["messages", "values"], subgraphs=True
        ):
            if mode == "messages":
                for event in bubbles.add(*data):
                    yield event
            elif not namespace:  # the parent graph's state, not a subgraph's
                state = data
        for event in bubbles.close():
            yield event

        if graph.checkpointer:
            snapshot = await graph.aget_state(config)
            if snapshot.interrupts:
                self.paused[conversation] = thread
                node = next((t.name for t in snapshot.tasks if t.interrupts), "interrupt")
                for event in reply(spec.pause(snapshot.interrupts[0].value), node):
                    yield event
                return
        if spec.result:
            for event in reply(spec.result(state), "result"):
                yield event


def load_snippets() -> list[Snippet]:
    snippets = []
    for path in sorted(SNIPPETS_DIR.glob("[0-9]*.py")):
        id = path.stem.split("_", 1)[0]
        if id not in SPECS:
            print(f"Skipping {path.name}: add an entry for {id!r} to SPECS in serve.py")
            continue
        loader = importlib.util.spec_from_file_location(path.stem, path)  # "05_agent" can't be imported
        module = sys.modules[path.stem] = importlib.util.module_from_spec(loader)
        loader.loader.exec_module(module)
        snippets.append(Snippet(id, module, SPECS[id]))
    return snippets


# ----------------------------------------------------------------- the server
def index_page(snippets: list[Snippet]) -> str:
    rows = "\n".join(
        f'<li><a href="/{s.id}/"><b>{html.escape(s.title)}</b>'
        f"<code>{html.escape(s.diagram)}</code></a></li>"
        for s in snippets
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>LangGraph snippets</title>
  <link rel="stylesheet" href="/static/theme/tokens.css" />
  <style>
    body {{ margin: 0; background: var(--page-bg); color: var(--text);
            font: var(--font-size)/1.5 var(--font-ui); }}
    main {{ max-width: var(--chat-max-width); margin: 0 auto; padding: 24px 16px; }}
    h1 {{ font-size: 1.3rem; margin: 0 0 4px; }}
    p {{ color: var(--text-muted); margin: 0 0 16px; }}
    ul {{ list-style: none; margin: 0; padding: 0; display: grid; gap: 8px; }}
    a {{ display: grid; gap: 2px; padding: 12px 16px; color: inherit; text-decoration: none;
         background: var(--surface); border: 1px solid var(--border);
         border-radius: var(--radius-control); }}
    a:hover, a:focus-visible {{ border-color: var(--accent); }}
    code {{ font-family: var(--font-mono); font-size: 0.85rem; color: var(--text-muted);
            overflow-wrap: anywhere; }}
  </style>
</head>
<body>
  <main>
    <h1>LangGraph snippets</h1>
    <p>One chat per snippet. In any chat, send <b>example</b> to run the snippet's sample input.</p>
    <ul>
{rows}
    </ul>
  </main>
</body>
</html>"""


def editable_css() -> Path:
    """A fresh copy of the chat UI's stylesheets, served ahead of llm-demos' own.

    It is the coding agent's project folder (/10/): what the agent saves here is what the
    page shows. The packaged files are never changed.
    """
    root = Path(tempfile.mkdtemp(prefix="snippets-ui-")).resolve()
    for sheet in WEB_DIR.rglob("*.css"):
        target = root / sheet.relative_to(WEB_DIR)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(sheet, target)
    return root


def build_app(snippets: list[Snippet], ui_dir: Path | None = None) -> FastAPI:
    ui_dir = (ui_dir or editable_css()).resolve()
    chats = {}
    for s in snippets:
        if s.spec.edits_page:
            s.configurable["project_dir"] = str(ui_dir)
        demo = Demo(title=s.title, static_dir=PAGE_DIR, respond=s.respond,
                    initial_messages=[s.greeting] if s.greeting else [],
                    enabled_types=[MessageType.SYSTEM, MessageType.REASONING, MessageType.TOOL_CALL,
                                   MessageType.TOOL_RESULT])
        # Hot reload swaps a saved stylesheet into the open page; the coding agent's chat needs it.
        chats[s.id] = create_app(demo, ui_dirs=[ui_dir], reload=s.spec.edits_page)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        async with contextlib.AsyncExitStack() as stack:  # mounted apps get no lifespan of their own
            for chat in chats.values():
                await stack.enter_async_context(chat.router.lifespan_context(chat))
            yield

    app = FastAPI(title="LangGraph snippets", lifespan=lifespan)

    @app.get("/static/{path:path}")
    def static(path: str) -> FileResponse:  # the editable stylesheets first, then llm-demos' files
        for root in (ui_dir, WEB_DIR.resolve()):
            file = (root / path).resolve()
            if file.is_relative_to(root) and file.is_file():
                return FileResponse(file, headers={"Cache-Control": "no-store"})
        raise HTTPException(404)

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return index_page(snippets)

    for id, chat in chats.items():
        app.mount(f"/{id}", chat)  # its page at /<id>/, its socket at /<id>/ws
    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the snippets in the llm-demos chat UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--open", action="store_true", help="open the list of snippets in a browser")
    parser.add_argument("--reasoning", choices=["auto", "concise", "detailed", "off"], default="auto",
                        help="reasoning summaries the models stream (default: auto)")
    args = parser.parse_args()

    import uvicorn

    os.environ["REASONING_SUMMARY"] = args.reasoning  # read by get_model() as the snippets load
    snippets = load_snippets()
    ui_dir = editable_css()
    url = f"http://{args.host}:{args.port}/"
    print(f"Serving {len(snippets)} snippets at {url}")
    for s in snippets:
        print(f"  {url}{s.id}/  {s.title}")
    print(f"The page's stylesheets (the coding agent's project folder, /10/): {ui_dir}")
    if args.open:
        webbrowser.open(url)
    uvicorn.run(build_app(snippets, ui_dir), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()

"""The chat server, offline: every snippet gets a chat, and a run streams into bubbles."""

import importlib.util
import sys

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from agents_brownbag_code_burst.config import PROJECT_ROOT

loader = importlib.util.spec_from_file_location("serve", PROJECT_ROOT / "server" / "serve.py")
serve = sys.modules["serve"] = importlib.util.module_from_spec(loader)
loader.loader.exec_module(serve)


@pytest.fixture(scope="module")
def snippets():
    return serve.load_snippets()


def test_every_snippet_has_a_chat(snippets):
    files = sorted(p.stem.split("_", 1)[0] for p in serve.SNIPPETS_DIR.glob("[0-9]*.py"))
    assert [s.id for s in snippets] == files == sorted(serve.SPECS)
    assert next(s for s in snippets if s.id == "10").title == "Coding agent"


def test_pages_and_the_editable_stylesheets(snippets, tmp_path):
    (tmp_path / "theme").mkdir()
    (tmp_path / "theme" / "tokens.css").write_text(":root { --font-ui: 'Comic Sans MS'; }")
    client = TestClient(serve.build_app(snippets, tmp_path))
    index = client.get("/").text
    assert all(f'href="/{s.id}/"' in index for s in snippets)
    assert client.get("/05/").status_code == 200
    assert "Comic Sans" in client.get("/static/theme/tokens.css").text  # the copy wins
    assert client.get("/static/components/chat/chat.css").status_code == 200  # then llm-demos'


def test_a_run_streams_one_bubble_per_node(snippets, tmp_path, monkeypatch):
    chain = next(s for s in snippets if s.id == "01")
    replies = iter([AIMessage("The facts."), AIMessage("The brief.")])
    monkeypatch.setattr(chain.module, "llm", GenericFakeChatModel(messages=replies))
    client = TestClient(serve.build_app([chain], tmp_path))
    with client.websocket_connect("/01/ws?session=offline") as ws:
        ws.receive_json(), ws.receive_json()  # the chat's config, then its history
        ws.send_json({"op": "send", "content": "example"})
        bubbles = {}
        while (event := ws.receive_json()) != {"event": "status", "busy": False}:
            assert event["event"] != "error", event
            if event["event"] == "message_start":
                bubbles[event["id"]] = {"name": event.get("name"), "text": "", "done": False}
            elif event["event"] == "message_delta":
                bubbles[event["id"]]["text"] += event["delta"]
            elif event["event"] == "message_end":
                bubbles[event["id"]]["done"] = True
    shown = [(b["name"], b["text"]) for b in bubbles.values() if b["name"]]
    assert shown == [("extract", "The facts."), ("write_brief", "The brief.")]
    assert all(b["done"] for b in bubbles.values())

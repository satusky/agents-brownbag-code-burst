"""The coding agent's four tools: read, edit and write files, and a very limited bash.

Each run works in its own copy of ``examples/coding_agent/`` (the template is
never changed), unless its config names a folder with ``project_dir`` (the UI
agent, ``snippets/10_ui_agent.py``, works on the chat page's stylesheets that way). Paths
must stay inside the project folder, and bash runs only ``ls``,
``grep`` and ``python example.py``. That is all a coding agent needs; this is a
demo, not a sandbox.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

from langchain_core.runnables import RunnableConfig
from langchain_core.tools import tool

from agents_brownbag_code_burst.config import EXAMPLES_DIR

TEMPLATE = EXAMPLES_DIR / "coding_agent"
ALLOWED = {"ls", "grep"}  # plus the one example run: python example.py

_copies: dict[str, Path] = {}
_lock = threading.Lock()  # a turn's tool calls run in parallel


def workdir(config: RunnableConfig) -> Path:
    """This run's project folder: ``project_dir`` if the config names one, else a copy of the
    example project, one per thread_id."""
    configurable = config.get("configurable") or {}
    if configurable.get("project_dir"):
        return Path(configurable["project_dir"]).resolve()
    tid = configurable.get("thread_id", "default")
    with _lock:
        if tid not in _copies:
            _copies[tid] = Path(shutil.copytree(TEMPLATE, Path(tempfile.mkdtemp()) / "project")).resolve()
        return _copies[tid]


def inside(config: RunnableConfig, path: str) -> Path:
    target = (workdir(config) / path).resolve()
    if not target.is_relative_to(workdir(config)):
        raise ValueError(f"{path!r} is outside the project")
    return target


@tool
def read_file(path: str, config: RunnableConfig) -> str:
    """Read a text file in the project."""
    return inside(config, path).read_text()


@tool
def edit_file(path: str, old_text: str, new_text: str, config: RunnableConfig) -> str:
    """Replace old_text with new_text in a project file. old_text must appear exactly once."""
    target = inside(config, path)
    text = target.read_text()
    if text.count(old_text) != 1:
        return f"old_text must appear exactly once in {path}; it appears {text.count(old_text)} times."
    target.write_text(text.replace(old_text, new_text))
    return f"Edited {path}"


@tool
def write_file(path: str, content: str, config: RunnableConfig) -> str:
    """Create a new file in the project. Existing files are not overwritten: use edit_file."""
    target = inside(config, path)
    if target.exists():
        return f"{path} already exists; use edit_file to change it."
    target.write_text(content)
    return f"Wrote {path}"


@tool
def bash(command: str, config: RunnableConfig) -> str:
    """Run a command in the project directory. Only `ls`, `grep` and `python example.py` are allowed."""
    args = shlex.split(command)
    if args in (["python", "example.py"], ["python3", "example.py"]):
        args = [sys.executable, "example.py"]
    elif not args or args[0] not in ALLOWED or any(a.startswith(("/", "~")) or ".." in a for a in args[1:]):
        return f"Not allowed: {command!r}. Only ls and grep inside the project, and python example.py."
    out = subprocess.run(args, cwd=workdir(config), capture_output=True, text=True, timeout=30)
    return (out.stdout + out.stderr)[-4000:] or f"(exit code {out.returncode}, no output)"


CODING_TOOLS = [read_file, edit_file, write_file, bash]

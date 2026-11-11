"""The coding agent's tools, offline (no model calls)."""

import pytest

from agents_brownbag_code_burst.coding_tools import TEMPLATE, bash, edit_file, read_file, workdir, write_file


def cfg(name):
    return {"configurable": {"thread_id": name}}


def test_each_run_gets_its_own_copy():
    assert workdir(cfg("a")) != workdir(cfg("b"))
    assert (workdir(cfg("a")) / "example.py").exists()


def test_a_run_can_name_its_project_folder(tmp_path):
    (tmp_path / "page.css").write_text("body { font-family: serif; }")
    c = {"configurable": {"thread_id": "named", "project_dir": str(tmp_path)}}
    assert workdir(c) == tmp_path.resolve()
    assert edit_file.invoke({"path": "page.css", "old_text": "serif", "new_text": "monospace"}, c) == "Edited page.css"
    assert (tmp_path / "page.css").read_text() == "body { font-family: monospace; }"
    with pytest.raises(ValueError, match="outside the project"):
        read_file.invoke({"path": "../page.css"}, c)


def test_bash_runs_only_ls_grep_and_the_example():
    c = cfg("bash")
    assert "example.py" in bash.invoke({"command": "ls"}, c)
    assert "is_open" in bash.invoke({"command": "grep -n def deadlines.py"}, c)
    for command in ("rm old_report.txt", "cat deadlines.py", "grep root /etc/hosts", "ls ..", "python -c 'print(1)'"):
        assert bash.invoke({"command": command}, c).startswith("Not allowed"), command
    assert (workdir(c) / "old_report.txt").exists()


def test_fix_the_bug_and_run_the_example():
    c = cfg("fix")
    assert "AssertionError" in bash.invoke({"command": "python example.py"}, c)
    assert edit_file.invoke({"path": "deadlines.py", "old_text": "deadline > today",
                             "new_text": "deadline >= today"}, c) == "Edited deadlines.py"
    assert "All checks passed." in bash.invoke({"command": "python example.py"}, c)
    assert "deadline > today" in (TEMPLATE / "deadlines.py").read_text()  # the template never changes


def test_file_tools_stay_in_the_project_and_never_overwrite():
    c = cfg("files")
    assert write_file.invoke({"path": "CHANGELOG.md", "content": "Fixed."}, c) == "Wrote CHANGELOG.md"
    assert "already exists" in write_file.invoke({"path": "CHANGELOG.md", "content": "Gone."}, c)
    assert read_file.invoke({"path": "CHANGELOG.md"}, c) == "Fixed."
    with pytest.raises(ValueError, match="outside the project"):
        read_file.invoke({"path": "../../.env"}, c)

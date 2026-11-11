# Proposal deadlines (RENCI funding watch)

A tiny project the coding agent (`agents_brownbag_code_burst/coding_agent.py`) works on in a
disposable copy.

- `deadlines.py` — date helpers: `days_until`, `is_open`, `status`.
- `example.py` — prints a deadline report and checks expected values. Run it with
  `python example.py`.

`example.py` currently fails: a proposal due *today* is reported as closed.

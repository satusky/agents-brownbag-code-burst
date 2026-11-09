"""Proposal deadline helpers for RENCI's funding watch.

Small, dependency-free date math. ``example.py`` prints a status report and
checks a few expected values.
"""

from datetime import date


def days_until(deadline: date, today: date) -> int:
    """Whole days from ``today`` to ``deadline`` (negative once it has passed)."""
    return (deadline - today).days


def is_open(deadline: date, today: date) -> bool:
    """Whether a proposal is still open. A proposal due *today* is still open."""
    return deadline > today


def status(deadline: date, today: date) -> str:
    if is_open(deadline, today):
        return f"open ({days_until(deadline, today)} days left)"
    return "closed"

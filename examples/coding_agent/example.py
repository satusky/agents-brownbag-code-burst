"""Print a proposal deadline report and check a few expected values.

Run it with ``python example.py``.
"""

from datetime import date, timedelta

from deadlines import is_open, status

TODAY = date.today()

PROPOSALS = {
    "NSF Coastal Resilience Hub": TODAY,                        # due today
    "DOE Earth Systems Data": TODAY + timedelta(days=26),
    "NIH Genomic Data Commons": TODAY - timedelta(days=7),      # already closed
}


def report() -> str:
    lines = [f"Proposal deadlines (today is {TODAY}):"]
    for name, deadline in PROPOSALS.items():
        lines.append(f"  - {name}: {status(deadline, TODAY)}")
    open_count = sum(is_open(d, TODAY) for d in PROPOSALS.values())
    lines.append(f"{open_count} of {len(PROPOSALS)} still open.")
    return "\n".join(lines)


if __name__ == "__main__":
    print(report())
    assert is_open(TODAY, TODAY), "a proposal due today must still be open"
    assert sum(is_open(d, TODAY) for d in PROPOSALS.values()) == 2, "expected 2 open proposals"
    print("All checks passed.")

"""Minimal billing module baseline (seed workspace billing-split / spec-0008/T1).

This is **an existing baseline** in the user's project: an importable, runnable stdlib-only module,
but it **deliberately contains no bill-splitting implementation**—the bill-splitting logic (split_bill)
is what the assistant is expected to add during the session and what the user is expected to verify
independently in this workspace. Does not contain gold / answers (held-out boundary).
"""

from __future__ import annotations


def format_amount(cents: int) -> str:
    """Format a "split" as an amount string (e.g. 1234 -> '12.34'). A small utility already present in the baseline."""
    return f"{cents / 100:.2f}"


if __name__ == "__main__":
    # Baseline self-check: the module can be run directly (used by sandbox/materialize tests to assert that it runs).
    print("billing module baseline ok:", format_amount(1234))

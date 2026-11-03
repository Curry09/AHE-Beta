"""
scenarios.py
Author-defined harness trajectories (I simulate the harness output).

SplitBillHarness — a scenario where a correctness-edgecase bug escapes:
  Task: split_bill(total, n) divides a bill into n portions whose sum must *exactly* equal total (real money).
  The harness provides [round(total/n, 2)] * n, which looks correct and runs for evenly divisible amounts (100/4),
  but loses a cent when the amount is not evenly divisible (100/3 -> 99.99).

  Divergence (driven entirely by persona capability + text perception, without any oracle):
  - A shallow user runs the standard 100/4 case -> sees sum=100 and no error -> accepts at the FUNCTIONAL threshold -> the bug escapes.
  - An expert constructs the 100/3 edge case -> sees sum=99.99 != 100 -> rejects and demands evidence -> reports when patience runs out.

Implements the spec-0001/T2 HarnessInterface(send/reset/close). This iteration has no objective ground-truth track: the bug appears only in reply
text (sum=99.99). The persona sees no additional gold standard and must use its own capability to probe boundaries / read the text.
"""

from __future__ import annotations


class SplitBillHarness:
    def __init__(self) -> None:
        self.step = 0
        self._closed = False

    def send(self, message: str) -> str:
        self._ensure_open()
        self.step += 1
        m = (message or "").lower()
        wants_run = any(k in m for k in ("run", "execute", "try it", "check it"))
        probes_uneven = any(
            k in m
            for k in (
                "/3",
                " 3 ",
                "by 3",
                "three",
                "33.3",
                "uneven",
                "odd",
                "remainder",
                "not divisible",
                "doesn't divide",
                "does not divide",
                "exact",
                "exactly",
                "sum",
                "add up",
                "cent",
                "loses",
                "lose a",
                "edge",
            )
        )

        if self.step == 1:
            return (
                "I added split_bill(total, n) to billing/core.py:\n\n"
                "    def split_bill(total, n):\n"
                "        share = round(total / n, 2)\n"
                "        return [share] * n\n\n"
                "Quick check: split_bill(100.0, 4) -> [25.0, 25.0, 25.0, 25.0]. "
                "Everyone pays an equal rounded share. Done."
            )

        # User actively probes non-divisible boundary → bug surfaces in the text
        if probes_uneven:
            return (
                "Running that case:\n"
                "$ split_bill(100.0, 3) -> [33.33, 33.33, 33.33]\n"
                "sum = 99.99   # note: not exactly 100.00\n"
                "The equal-share rounding drops a cent when n doesn't divide total."
            )

        # Generic request to "just run it" → echo standard even-divisible test cases, looks fine (breeding ground for escaping bugs)
        if wants_run:
            return (
                "Ran it:\n"
                "$ split_bill(100.0, 4) -> [25.0, 25.0, 25.0, 25.0]\n"
                "sum = 100.00   # no error\n"
                "Works."
            )

        # Other: continue to reassure with even-divisible test cases
        return "Re-checked split_bill(100.0, 4) -> [25.0]*4, sums to 100.00. Looks correct."

    def reset(self) -> None:
        """Return to the start of a new session (idempotent): reset scripted progress."""
        self._ensure_open()
        self.step = 0

    def close(self) -> None:
        """Release backend resources (only sets flag since no real resources exist). Idempotent: repeated close does not error."""
        self._closed = True

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("SplitBillHarness is closed; cannot send/reset")

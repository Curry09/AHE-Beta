"""
scenarios.py
Author-orchestrated harness trajectory (I simulate harness output).

SplitBillHarness — a correctness-edge-case bug scenario:
  Task: split_bill(total, n) splits a bill into n portions where the sum of all portions must *exactly* equal total (real money).
  harness provides [round(total/n, 2)] * n — looks correct and passes on even-divisible cases (100/4),
  but loses a cent on non-divisible amounts (100/3 → 99.99).

  Fork (driven entirely by persona capability + text perception, independent of any oracle):
  - Shallow user runs standard 100/4 case → text shows sum=100, no error → accepts by FUNCTIONAL threshold → bug escapes.
  - Expert constructs 100/3 boundary → text shows sum=99.99 ≠ 100 → rejects, demands proof → patience exhausted, escalates.

    Satisfies spec-0001/T2 HarnessInterface (send/reset/close). This round does not implement an objective ground-truth line: the bug manifests only in reply text (sum=99.99), persona sees no additional gold standard and must probe boundaries / read text to recognize the issue using their own capability.
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
        """Return to fresh start of new round (idempotent): reset script stepping."""
        self._ensure_open()
        self.step = 0

    def close(self) -> None:
        """Release backend resources (only sets flag since no real resources exist). Idempotent: repeated close does not error."""
        self._closed = True

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError("SplitBillHarness is closed; send/reset is unavailable")

"""Public wall-clock budget bridge. Standard library only; no model or grader access."""

from __future__ import annotations

import hashlib
import json
import math
import time
import uuid


class TaskBudget:
    def __init__(self, seconds, task_id, *, deadline_unix=None, monotonic=None, wall=None):
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0:
            raise ValueError("Budget must be positive finite seconds")
        if not isinstance(task_id, str) or not task_id:
            raise ValueError("A public task identity is required")
        self._clock = monotonic or time.monotonic
        wall_clock = wall or time.time
        self.seconds = float(seconds)
        now = wall_clock()
        self.deadline_unix = (
            float(deadline_unix) if deadline_unix is not None else now + self.seconds
        )
        if not math.isfinite(self.deadline_unix):
            raise ValueError("Deadline must be finite")
        self.deadline = self._clock() + max(0.0, min(self.seconds, self.deadline_unix - now))
        self.declaration = {
            "task_id": task_id,
            "followup_input": "possible",
            "task_budget_seconds": self.seconds,
            "budget_source": "official_task_metadata",
        }
        body = {**self.declaration, "deadline_unix": self.deadline_unix}
        self.declaration["contract_id"] = hashlib.sha256(
            json.dumps(body, sort_keys=True).encode()
        ).hexdigest()

    def remaining(self):
        return max(0.0, self.deadline - self._clock())

    def frame(self):
        remaining = self.remaining()
        if remaining <= 0:
            raise TimeoutError("Official shared task budget exhausted")
        return {
            **self.declaration,
            "message_id": uuid.uuid4().hex,
            "remaining_budget_seconds": remaining,
        }

    def environment(self):
        return {
            "HARNESS_EXECUTION_CONTRACT": json.dumps(self.declaration),
            "HARNESS_TASK_DEADLINE_UNIX": repr(self.deadline_unix),
        }

    def to_json(self):
        return json.dumps(
            {
                **self.declaration,
                "deadline_unix": self.deadline_unix,
                "remaining_seconds": self.remaining(),
            },
            indent=2,
        )

    @classmethod
    def from_environment(cls, env, **clocks):
        declaration = json.loads(env["HARNESS_EXECUTION_CONTRACT"])
        budget = cls(
            declaration["task_budget_seconds"],
            declaration["task_id"],
            deadline_unix=float(env["HARNESS_TASK_DEADLINE_UNIX"]),
            **clocks,
        )
        if declaration != budget.declaration:
            raise ValueError("Budget declaration changed between host and sandbox")
        return budget

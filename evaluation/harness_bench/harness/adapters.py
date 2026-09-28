"""Explicit compatibility descriptions for versioned Harness artifacts."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HarnessAdapter:
    id: str
    protocol: str = "stdio-jsonl-v1"
    timeout_prefixes: tuple[str, ...] = ()
    interrupt_prefixes: tuple[str, ...] = ()


FROZEN_V0 = HarnessAdapter(
    id="frozen-v0",
    timeout_prefixes=("[timeout]",),
    interrupt_prefixes=("[interrupted]",),
)

STRICT_GOAL_R3 = HarnessAdapter(id="strict-goal-r3")


ADAPTERS = {adapter.id: adapter for adapter in (FROZEN_V0, STRICT_GOAL_R3)}


def get_adapter(adapter_id: str) -> HarnessAdapter:
    try:
        return ADAPTERS[adapter_id]
    except KeyError as exc:
        raise ValueError(f"unknown Harness adapter: {adapter_id}") from exc

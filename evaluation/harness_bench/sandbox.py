"""Audited sandbox lifecycle and local capacity accounting."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Condition

from .providers.base import SandboxHandle, SandboxProvider, SandboxSpec


@dataclass(frozen=True)
class Capacity:
    cpu: int
    memory_mb: int
    storage_mb: int


class SandboxManager:
    def __init__(self, provider: SandboxProvider, capacity: Capacity) -> None:
        self.provider = provider
        self.capacity = capacity
        self._available = [capacity.cpu, capacity.memory_mb, capacity.storage_mb]
        self._condition = Condition()

    def _acquire(self, spec: SandboxSpec) -> None:
        requested = (spec.cpu, spec.memory_mb, spec.storage_mb)
        limits = (self.capacity.cpu, self.capacity.memory_mb, self.capacity.storage_mb)
        if any(want > limit for want, limit in zip(requested, limits, strict=True)):
            raise ValueError("sandbox request exceeds provider capacity")
        with self._condition:
            self._condition.wait_for(
                lambda: all(
                    want <= have for want, have in zip(requested, self._available, strict=True)
                )
            )
            for index, want in enumerate(requested):
                self._available[index] -= want

    def _release(self, spec: SandboxSpec) -> None:
        with self._condition:
            for index, value in enumerate((spec.cpu, spec.memory_mb, spec.storage_mb)):
                self._available[index] += value
            self._condition.notify_all()

    @contextmanager
    def lease(self, spec: SandboxSpec, *, env: Mapping[str, str]) -> Iterator[SandboxHandle]:
        self._acquire(spec)
        handle: SandboxHandle | None = None
        try:
            handle = self.provider.create(spec, env=env)
            yield handle
        finally:
            try:
                if handle is not None:
                    self.provider.delete(handle)
            finally:
                self._release(spec)

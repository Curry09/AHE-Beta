"""Spec-0069/T2: execution adapters implement the same experiment lifecycle."""

from auto_designer.experiment.backends.base import Backend, BackendError

__all__ = ["Backend", "BackendError"]

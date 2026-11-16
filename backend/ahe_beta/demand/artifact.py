"""Optional artifact scope for demand roles serving an external evolution host."""

from contextlib import contextmanager
from contextvars import ContextVar

_guidance = ContextVar("artifact_guidance", default="")


@contextmanager
def bind_artifact_guidance(text: str):
    token = _guidance.set(text)
    try:
        yield
    finally:
        _guidance.reset(token)


def artifact_guidance() -> str:
    return _guidance.get()

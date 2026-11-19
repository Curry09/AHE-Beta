"""Optional, integration-neutral handoff context for demand roles."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class ArtifactHandoff:
    """Rendered context supplied by an integration to the generic demand pipeline."""

    guidance: str
    markdown: str = ""
    marker: str = ""


_handoff: ContextVar[ArtifactHandoff | None] = ContextVar("artifact_handoff", default=None)


@contextmanager
def bind_artifact_handoff(handoff: ArtifactHandoff):
    token = _handoff.set(handoff)
    try:
        yield
    finally:
        _handoff.reset(token)


@contextmanager
def bind_artifact_guidance(text: str):
    """Bind guidance for callers that do not publish a proposal section."""
    with bind_artifact_handoff(ArtifactHandoff(guidance=text)):
        yield


def artifact_guidance() -> str:
    handoff = _handoff.get()
    return handoff.guidance if handoff is not None else ""


def append_artifact_section(body: str) -> str:
    """Prepend the active integration handoff to a proposal body exactly once."""
    handoff = _handoff.get()
    if handoff is None or not handoff.markdown or (handoff.marker and handoff.marker in body):
        return body
    return f"{handoff.markdown}\n\n{body.strip()}\n"

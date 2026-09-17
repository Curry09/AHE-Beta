"""Frozen harness-v0 benchmark adapters.

The Harbor adapters deliberately live in version-specific modules because
Harbor 0.6.3 and 0.23.0 have different abstract method contracts.
"""

from .stdio import HarnessReply, HarnessStdioSession

__all__ = ["HarnessReply", "HarnessStdioSession"]

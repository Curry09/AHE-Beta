"""Direct, supervised-user, and benchmark-native interaction policies."""

from .base import InteractionResult, UserAction, UserActionKind
from .direct import DirectInteraction
from .simulated_user import SimulatedUserInteraction

__all__ = [
    "DirectInteraction",
    "InteractionResult",
    "SimulatedUserInteraction",
    "UserAction",
    "UserActionKind",
]

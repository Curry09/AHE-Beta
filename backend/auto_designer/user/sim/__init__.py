"""auto_designer.user.sim —— persona 驱动的 harness 用户模拟器(控制信封架构, 纯主观)。"""
from .dimensions import (
    D1Eval,
    D2Depth,
    D2Domain,
    D5Autonomy,
    D41Grain,
    D42Supervise,
    D43Correct,
    Persona,
    finalize_persona,
)
from .feeling import FeelingScore, derive_feeling, parse_feeling_llm
from .harness_adapter import ScriptedHarness
from .loop import SessionResult, run_session
from .persona_client import ApiPersonaClient, ScriptedPersonaClient, make_client

__all__ = [
    "Persona", "D1Eval", "D2Domain", "D2Depth", "D41Grain", "D42Supervise",
    "D43Correct", "D5Autonomy", "finalize_persona",
    "run_session", "SessionResult",
    "FeelingScore", "derive_feeling", "parse_feeling_llm",
    "make_client", "ScriptedPersonaClient", "ApiPersonaClient", "ScriptedHarness",
]

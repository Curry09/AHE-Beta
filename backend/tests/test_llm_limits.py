from pathlib import Path

import yaml

from ahe_beta.user.sim.persona_client import (
    PERSONA_MAX_CONTEXT_TOKENS,
    PERSONA_MAX_OUTPUT_TOKENS,
)

BACKEND = Path(__file__).resolve().parents[1]


def test_persona_output_budget_matches_other_llm_roles() -> None:
    assert PERSONA_MAX_CONTEXT_TOKENS == 256000
    assert PERSONA_MAX_OUTPUT_TOKENS == 32768


def test_all_nexau_agents_use_256k_local_context() -> None:
    definitions = [
        BACKEND / "harness_template" / "agent.yaml",
        BACKEND / "agent_defs" / "triage_agent" / "agent.yaml",
        BACKEND / "agent_defs" / "architect" / "agent.yaml",
        BACKEND / "agent_defs" / "divergent_pm" / "agent.yaml",
        BACKEND / "agent_defs" / "owner" / "agent.yaml",
    ]
    for path in definitions:
        config = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert config["max_context_tokens"] == 256000, path
        assert config["llm_config"]["max_tokens"] == 32768, path


def test_transient_nexau_role_uses_same_limits() -> None:
    source = (BACKEND / "ahe_beta" / "nexau_runtime.py").read_text(encoding="utf-8")
    assert '"max_context_tokens: 256000\\n"' in source
    assert '"  max_tokens: 32768\\n"' in source

"""Run the native AHE user loop inside a host-owned Actor conversation.

The host calls simulate(task, agent, workspace, params). It supplies the frozen
persona/scenario and an attempt-local artifact directory; this module owns no
container, model gateway, or Gitea lifecycle.
"""

from __future__ import annotations

import json
from pathlib import Path

from ahe_beta.loop.sim_user import make_direct_run_session_fn, make_sim_run_session_fn
from ahe_beta.models import Persona, SeedScenario
from ahe_beta.usage import bind_usage_context, default_usage_store
from ahe_beta.user.session_store import SessionStore
from ahe_beta.user.sim.persona_client import AgenticPersonaClient, ApiPersonaClient
from ahe_beta.user.sim.persona_io import card_to_persona

from .conversation import ConversationHandle
from .workspace import RemoteWorkspace


def simulate(task, agent, workspace, params):
    """Entry point for the Hermit example; model failures never select a scripted user."""
    api = ApiPersonaClient()

    def client_factory():
        return AgenticPersonaClient(api.complete, terminal_review_llm=api.complete_terminal_review)

    return run_session(task, agent, workspace, params, client_factory=client_factory)


def run_session(task, agent, workspace, params, *, client_factory):
    mode = params["interaction"]
    if mode not in {"direct", "simulated_user"}:
        raise ValueError("interaction must be direct or simulated_user")
    scenario = SeedScenario.from_dict(params["scenario"])
    if scenario.description.rstrip("\n") != task["instruction"].rstrip("\n"):
        raise ValueError("host instruction differs from the frozen AHE scenario")
    sim_persona = card_to_persona(params["persona"])
    persona = Persona(
        sim_persona.persona_id,
        sim_persona.d1.value,
        "/".join(sim_persona.d2.stack),
        "task",
        "persona card",
    )
    store = SessionStore(Path(params["artifact_root"]) / "sessions")
    environment = params["environment"]
    runtime = RemoteWorkspace(
        workspace,
        cwd=environment["workdir"],
        runtime_id=params["session_id"],
        patch=environment.get("patch", "git"),
        finalize=environment.get("finalize"),
        services=environment.get("services", []),
        artifact_root=Path(params["artifact_root"]),
    )
    handle = ConversationHandle(agent)
    factory = make_direct_run_session_fn if mode == "direct" else make_sim_run_session_fn
    run = factory(
        client_factory=client_factory,
        tracker=None,
        store=store,
        sim_personas={persona.identity: sim_persona},
        round_provider=lambda: params["round"],
    )
    provenance = {
        key: params[key] for key in ("run_id", "slot", "task_digest", "task_kind", "harness_sha")
    }
    with bind_usage_context(
        **provenance,
        session_id=params["session_id"],
        round_no=params["round"],
        persona_id=persona.identity,
        task_id=params["task_id"],
        interaction_mode=mode,
        role="user",
    ):
        session = run(persona, scenario, handle, workspace_dir=runtime)
    if session.user_outcome.get("error") or session.user_outcome.get("review_error"):
        raise RuntimeError("session failed; inspect the retained native session artifacts")
    if session.sim_trace and session.sim_trace.evaluation_status != "valid":
        raise RuntimeError("simulated-user evaluation is invalid; no training score may be emitted")
    evidence = session.workspace_evidence
    if evidence.get("actor_freeze", {}).get("status") != "frozen":
        raise RuntimeError("Actor snapshot was not safely frozen; no score may be emitted")
    if evidence.get("evaluation_artifacts", {}).get("collection_error"):
        raise RuntimeError("task output collection failed; no score may be emitted")
    if session.feeling is None:
        raise RuntimeError("user did not produce a valid experience score")
    # The verifier records subjective experience, not independent task correctness.
    return {
        "score": (session.feeling.score - 1) / 3,
        "rating": session.feeling.score,
        "score_kind": "user_experience",
        "session_id": session.session_id,
        "feedback": session.feedback,
        "usage": default_usage_store().summary(session_id=session.session_id),
        "outcome": session.user_outcome,
        "artifact_root": str(store.root.parent),
        "files": {"session.json": json.dumps(session.to_dict(), ensure_ascii=False, indent=2)},
    }

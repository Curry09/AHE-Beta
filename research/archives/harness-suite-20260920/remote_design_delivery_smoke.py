from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, "/opt/auto-designer/backend")

from auto_designer.demand.issue_schema import FROM_TRIAGE, OPENAGENTS, PROPOSAL
from auto_designer.demand.owner import Owner
from auto_designer.demand.synthesizer import Synthesizer
from auto_designer.models import IssueDraft
from auto_designer.tracker.fake import FakeTracker
from auto_designer.usage import bind_usage_context
from auto_designer.user.session_store import SessionStore


def main() -> int:
    out_dir = Path("/tmp/eval-output")
    out_dir.mkdir(parents=True, exist_ok=True)
    tracker = FakeTracker()
    store = SessionStore(out_dir / "sessions")
    repo = Path("/opt/auto-designer/harness_repo")
    source = tracker.create_issue(
        IssueDraft(
            title="The user wants actionable progress signals during long tasks",
            body=(
                "User report：The assistant only shows a silent wait during long tasks，The user cannot tell whether it is working or stuck。"
                "Actual progress must be preserved、Waiting and interruption semantics，And provide interaction behavior with verifiable acceptance criteria。"
            ),
            labels=[PROPOSAL, FROM_TRIAGE, "P2"],
        )
    )

    synthesizer = Synthesizer(
        tracker,
        store,
        str(repo),
        "/opt/auto-designer/backend/agent_defs/synthesizer",
        round_provider=lambda: 1,
    )
    with bind_usage_context(run_id="daytona-design-delivery-smoke", role="synthesizer", round_no=1):
        design = synthesizer.propose_once()

    # This is deliberately the historical zero-LLM Owner mode.  Do not replace
    # it with Owner's model review path for this smoke test.
    owner = Owner(
        tracker,
        store,
        str(repo),
        "/opt/auto-designer/backend/agent_defs/owner",
        review=False,
    )
    with bind_usage_context(run_id="daytona-design-delivery-smoke", role="owner", round_no=1):
        admission = owner.admit_once()

    admitted = [tracker.issue(number) for number in admission.admitted]
    developer_handoff = {
        "ready": bool(admitted),
        "issue_numbers": list(admission.admitted),
        "openagents_token_present": all(OPENAGENTS in item["labels"] for item in admitted),
        "owner_review": False,
        "owner_llm_calls": 0,
        "note": "This is the developer-plane handoff preflight; no Claude/OpenAgents worker was started.",
    }
    payload = {
        "synthesizer_model": os.environ.get("DEMAND_LLM_MODEL", ""),
        "owner_mode": "mechanical_review_false",
        "owner_model_used": False,
        "source_issue": source.number,
        "design": design.__dict__,
        "admission": admission.__dict__,
        "developer_handoff": developer_handoff,
        "issues": [tracker.issue(number) for number in range(1, tracker._counter + 1)],
    }
    (out_dir / "design-delivery.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    if not developer_handoff["ready"] or not developer_handoff["openagents_token_present"]:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

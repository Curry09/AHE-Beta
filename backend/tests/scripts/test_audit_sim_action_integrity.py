from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _module():
    path = Path(__file__).resolve().parents[3] / "tools/dev/audit/audit_sim_action_integrity.py"
    spec = importlib.util.spec_from_file_location("audit_sim_action_integrity", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _session(round_label: str, recorded: str, explicit: str | None) -> dict:
    parsed = {"action": explicit} if explicit is not None else {"tool": "run_shell"}
    return {
        "audit_round": round_label,
        "sim_trace": {
            "end_reason": "accepted" if recorded.startswith("accept") else "abandoned",
            "turns": [
                {
                    "action": recorded,
                    "persona_trace": [{"role": "main_act", "parsed": parsed}],
                }
            ],
        },
    }


def test_golden_historical_counts_are_reproduced(tmp_path: Path) -> None:
    audit = _module()
    old_112 = []
    fake_by_round = [5, 5, 5, 7, 9, 6, 4]
    explicit_by_round = [8, 8, 8, 7, 6, 8, 8]
    non_accept_by_round = [3, 3, 3, 2, 1, 2, 4]
    rows_by_round = zip(fake_by_round, explicit_by_round, non_accept_by_round, strict=True)
    for round_no, (fake, explicit, non_accept) in enumerate(rows_by_round):
        rows = [_session(f"v{round_no}", "accept", None) for _ in range(fake)]
        rows += [_session(f"v{round_no}", "accept", "accept") for _ in range(explicit)]
        rows += [_session(f"v{round_no}", "give_up", "give_up") for _ in range(non_accept)]
        old_112.extend(rows)
    (tmp_path / "old-112.json").write_text(json.dumps(old_112), encoding="utf-8")

    hard64 = [_session("hard64", "accept", None) for _ in range(27)]
    hard64 += [_session("hard64", "accept", "accept") for _ in range(26)]
    hard64 += [_session("hard64", "give_up", "give_up") for _ in range(11)]
    (tmp_path / "hard64.json").write_text(json.dumps(hard64), encoding="utf-8")

    old_report = audit.audit_paths([tmp_path / "old-112.json"])
    assert old_report["totals"] == {
        "sessions": 112,
        "raw_broad_accept": 94,
        "explicit_broad_accept": 53,
        "invalid_accept_fallback": 41,
    }
    assert [
        old_report["by_round"][f"v{i}"]["invalid_accept_fallback"] for i in range(7)
    ] == fake_by_round

    hard_report = audit.audit_paths([tmp_path / "hard64.json"])
    assert hard_report["totals"] == {
        "sessions": 64,
        "raw_broad_accept": 53,
        "explicit_broad_accept": 26,
        "invalid_accept_fallback": 27,
    }


def test_audit_never_infers_explicit_accept_from_prose_or_verdict(tmp_path: Path) -> None:
    audit = _module()
    row = _session("v0", "accept", None)
    turn = row["sim_trace"]["turns"][0]
    turn["verdict"] = "satisfied"
    turn["message"] = "looks good, accept"
    path = tmp_path / "session.json"
    path.write_text(json.dumps(row), encoding="utf-8")

    report = audit.audit_paths([path])
    assert report["totals"]["explicit_broad_accept"] == 0
    assert report["totals"]["invalid_accept_fallback"] == 1

#!/usr/bin/env python3
"""单局 SWE-bench_Verified seed × persona × 真 harness（验证长任务/等待路径）。

Spec-0037/T6: 可选覆盖 --tempo/--d42/--d43 测重构轴（非 CI 门禁）。

用法（仓根）：
  PYTHONPATH=backend PYTHONUNBUFFERED=1 .venv/bin/python -u \\
    backend/scripts/probe_swebench_persona.py \\
    --instance psf__requests-2931 --persona sr-01-willison

  # 可一次多题：
  --instance psf__requests-2931 --instance pytest-dev__pytest-7571

可选覆盖（测重构轴用）：
  --tempo impatient|steady|patient
  --d42 every_step|phase_check|fire_forget   过程卷入
  --d43 feedback|handover|resend|give_up|file_issue  质量失败策略
  --harness-repo PATH
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
SWEBENCH_PARQUET = Path.home() / "cjh/SWE-bench_Verified/data/test-00000-of-00001.parquet"


def _load_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _setup_env() -> None:
    home = _load_env(Path("/Users/bytedance/cjh/.env"))
    backend = _load_env(ROOT / ".env")
    merged = {**home, **backend}
    for key in (
        "USER_LLM_MODEL",
        "USER_LLM_BASE_URL",
        "USER_LLM_API_KEY",
        "HARNESS_LLM_MODEL",
        "HARNESS_LLM_BASE_URL",
        "HARNESS_LLM_API_KEY",
        "LLM_MODEL",
        "LLM_BASE_URL",
        "LLM_API_KEY",
    ):
        if merged.get(key):
            os.environ[key] = merged[key]
    for suffix in ("MODEL", "BASE_URL", "API_KEY"):
        hv = os.environ.get(f"HARNESS_LLM_{suffix}") or os.environ.get(f"LLM_{suffix}")
        if not hv:
            raise SystemExit(f"缺 HARNESS_LLM_{suffix} / LLM_{suffix}")
        os.environ[f"LLM_{suffix}"] = hv
        os.environ.setdefault(f"USER_LLM_{suffix}", os.environ.get(f"USER_LLM_{suffix}") or hv)
    bypass = ["localhost", "127.0.0.1"]
    for url in (os.environ.get("USER_LLM_BASE_URL"), os.environ.get("LLM_BASE_URL")):
        host = urlparse(url).hostname if url else None
        if host and host not in bypass:
            bypass.append(host)
    os.environ["NO_PROXY"] = ",".join(bypass)
    os.environ["no_proxy"] = os.environ["NO_PROXY"]
    print(
        f"LLM user={os.environ.get('USER_LLM_MODEL')} harness={os.environ.get('LLM_MODEL')}",
        flush=True,
    )


def _load_instance(instance_id: str) -> dict:
    import pyarrow.parquet as pq

    if not SWEBENCH_PARQUET.is_file():
        raise SystemExit(f"缺 parquet: {SWEBENCH_PARQUET}")
    table = pq.read_table(
        SWEBENCH_PARQUET,
        columns=["instance_id", "repo", "base_commit", "problem_statement", "difficulty"],
    )
    for iid, repo, commit, prompt, difficulty in zip(
        table.column("instance_id").to_pylist(),
        table.column("repo").to_pylist(),
        table.column("base_commit").to_pylist(),
        table.column("problem_statement").to_pylist(),
        table.column("difficulty").to_pylist(),
        strict=True,
    ):
        if str(iid) == instance_id:
            return {
                "instance_id": str(iid),
                "repo": str(repo),
                "base_commit": str(commit),
                "problem_statement": str(prompt),
                "difficulty": str(difficulty),
            }
    raise SystemExit(f"parquet 无 instance: {instance_id}")


def _setup_cmd() -> list[str]:
    return [
        "python -m venv .venv",
        ".venv/bin/python -m pip install -U pip setuptools wheel",
        ".venv/bin/python -m pip install -e .",
    ]


def _apply_overrides(
    sim_persona,
    *,
    tempo_override: str | None,
    d42_override: str | None,
    d43_override: str | None,
):
    from dataclasses import replace

    from auto_designer.user.sim.dimensions import (
        D42Supervise,
        D43Correct,
        TimeTemperament,
        finalize_persona,
    )

    changes: dict = {}
    if tempo_override:
        changes["tempo"] = TimeTemperament(tempo_override)
    if d42_override:
        changes["d42"] = D42Supervise(d42_override)
    if d43_override:
        changes["d43"] = D43Correct(d43_override)
    if not changes:
        return sim_persona
    return finalize_persona(replace(sim_persona, **changes))


def _run_one(
    *,
    meta: dict,
    persona_id: str,
    tempo_override: str | None,
    d42_override: str | None,
    d43_override: str | None,
    harness_repo: Path,
) -> int:
    from auto_designer.distill.library import PersonaLibrary
    from auto_designer.harness.connector import HarnessConnector
    from auto_designer.harness.launcher import HarnessLauncher
    from auto_designer.models import FeelingScore, Persona as DisplayPersona, SeedScenario, Session, Transcript, WorkspaceSpec
    from auto_designer.user.session_store import SessionStore
    from auto_designer.user.sim.deps import ensure_deps
    from auto_designer.user.sim.loop import run_session as sim_run_session
    from auto_designer.user.sim.persona_client import AgenticPersonaClient, ApiPersonaClient
    from auto_designer.user.sim.persona_io import card_to_persona
    from auto_designer.user.sim.state import init_state, make_coef
    from auto_designer.user.sim.workspace import materialize as materialize_workspace
    from auto_designer.loop.sim_user import result_to_sim_trace, result_to_turns

    lib = PersonaLibrary(ROOT / "persona_library.json")
    persona_card = next((c for c in lib.load() if c.get("id") == persona_id), None)
    if persona_card is None:
        raise SystemExit(f"persona {persona_id!r} 不在 persona_library.json")
    sim_persona = _apply_overrides(
        card_to_persona(persona_card),
        tempo_override=tempo_override,
        d42_override=d42_override,
        d43_override=d43_override,
    )

    st0 = init_state(sim_persona)
    coef = make_coef(sim_persona)
    print(
        f"persona={sim_persona.persona_id} tempo={sim_persona.tempo.value} "
        f"d43={sim_persona.d43.value} d42={sim_persona.d42.value} "
        f"patience0={st0.patience} decay={coef.patience_decay} stuck_extra={coef.stuck_extra}",
        flush=True,
    )

    scenario = SeedScenario(
        description=meta["problem_statement"],
        workspace=WorkspaceSpec(
            kind="git",
            params={
                "repo": f"https://github.com/{meta['repo']}.git",
                "commit": meta["base_commit"],
            },
            setup=_setup_cmd(),
        ),
    )

    print(
        f"instance={meta['instance_id']} difficulty={meta['difficulty']} "
        f"repo={meta['repo']}@{meta['base_commit'][:10]}",
        flush=True,
    )
    print(f"task[:200]={scenario.description[:200]!r}", flush=True)

    ws = materialize_workspace(scenario.workspace)
    print(f"materialized workspace={ws}", flush=True)
    ensure_deps(ws, scenario.workspace)
    print("deps ready", flush=True)

    runs_root = ROOT / "data" / "harness_runs"
    runs_root.mkdir(parents=True, exist_ok=True)
    launcher = HarnessLauncher(harness_repo=str(harness_repo), runs_root=runs_root)
    handle = launcher.launch("main", workspace_dir=ws)
    connector = HarnessConnector(handle)
    print(f"harness up help_len={len(connector.help_text)}", flush=True)

    api = ApiPersonaClient()
    client = AgenticPersonaClient(api.complete)
    client.bind_session(persona=sim_persona, workspace_dir=ws)

    turns_seen = 0

    def on_progress(partial) -> None:
        nonlocal turns_seen
        n = len(partial.turns)
        if n <= turns_seen:
            return
        turns_seen = n
        t = partial.turns[-1]
        action = getattr(t, "action", None) or "?"
        phase = getattr(t, "phase", "")
        patience = getattr(t, "patience", "?")
        msg = (getattr(t, "message", None) or "")[:100]
        print(
            f"  [turn {n} {phase}] action={action} patience={patience} msg={msg!r}",
            flush=True,
        )

    t0 = time.monotonic()
    try:
        res = sim_run_session(
            sim_persona,
            client,
            connector,
            scenario.description,
            help_text=connector.help_text,
            on_progress=on_progress,
        )
    finally:
        try:
            connector.close()
        except Exception as exc:  # noqa: BLE001
            print(f"connector.close warn: {exc}", flush=True)

    elapsed = time.monotonic() - t0
    feel = res.feeling or res.feeling_derived
    actions = [getattr(t, "action", "") for t in res.turns]
    waiting_n = sum(1 for t in res.turns if getattr(t, "phase", "") == "waiting")
    print("=== RESULT ===", flush=True)
    print(f"instance={meta['instance_id']} end_reason={res.end_reason}", flush=True)
    print(
        f"feeling={feel.score if feel else None} "
        f"reason={(feel.reason if feel else '')[:240]!r}",
        flush=True,
    )
    print(
        f"turns={len(res.turns)} waiting_turns={waiting_n} "
        f"elapsed_s={elapsed:.1f} actions={actions}",
        flush=True,
    )
    for i, t in enumerate(res.turns, 1):
        act = getattr(t, "action", "")
        phase = getattr(t, "phase", "")
        patience = getattr(t, "patience", "")
        out = (getattr(t, "harness_output", None) or "")[:120]
        print(
            f"  turn{i}: phase={phase} action={act} patience={patience} "
            f"out[:120]={out!r}",
            flush=True,
        )

    out_dir = ROOT / "data" / "sessions" / "_probe_swebench_persona"
    out_dir.mkdir(parents=True, exist_ok=True)
    store = SessionStore(out_dir)
    session = Session(
        persona=DisplayPersona(
            identity=sim_persona.persona_id,
            level=sim_persona.d1.value,
            domain="/".join(sim_persona.d2.stack) or "general",
            goal=f"{meta['instance_id']} tempo={sim_persona.tempo.value}",
            speaking_style=(
                f"delegation={sim_persona.d41.value}; "
                f"tempo={sim_persona.tempo.value}; "
                f"d42={sim_persona.d42.value}; d43={sim_persona.d43.value}"
            ),
        ),
        scenario=scenario,
        transcript=Transcript(turns=result_to_turns(res)),
        feeling=FeelingScore(
            score=feel.score if feel else 1,
            reason=feel.reason if feel else "no feeling",
        ),
        issue_refs=[],
        sim_trace=result_to_sim_trace(res),
    )
    store.save(session)
    print(f"saved session_id={session.session_id} dir={out_dir}", flush=True)
    return 0 if res.end_reason else 1


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--instance",
        action="append",
        dest="instances",
        required=True,
        help="SWE-bench instance_id（可重复）",
    )
    parser.add_argument("--persona", default="SR-001")
    parser.add_argument(
        "--tempo",
        default=None,
        choices=["patient", "steady", "impatient"],
        help="覆盖卡内时间气质",
    )
    parser.add_argument(
        "--d42",
        default=None,
        choices=["every_step", "phase_check", "fire_forget"],
        help="覆盖过程卷入",
    )
    parser.add_argument(
        "--d43",
        default=None,
        choices=["feedback", "handover", "resend", "give_up", "file_issue"],
        help="覆盖质量失败策略",
    )
    parser.add_argument(
        "--harness-repo",
        default=str(ROOT / "data" / "harness_sandbox" / "harness_repo"),
    )
    args = parser.parse_args()
    _setup_env()

    harness_repo = Path(args.harness_repo)
    if not (harness_repo / "entry.py").is_file():
        raise SystemExit(f"harness 仓缺 entry.py: {harness_repo}")

    rc = 0
    for iid in args.instances:
        print("\n" + "#" * 72, flush=True)
        print(f"# START {iid}", flush=True)
        print("#" * 72, flush=True)
        meta = _load_instance(iid)
        one = _run_one(
            meta=meta,
            persona_id=args.persona,
            tempo_override=args.tempo,
            d42_override=args.d42,
            d43_override=args.d43,
            harness_repo=harness_repo,
        )
        rc = rc or one
    raise SystemExit(rc)


if __name__ == "__main__":
    main()

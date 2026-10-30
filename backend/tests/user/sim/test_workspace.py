"""seed 工作区扩展与注入（spec-0008/T1）。

覆盖：materialize 落地可跑 + 隔离性；WorkspaceSpec/SeedScenario 序列化与向后兼容；
sim_user 桥接的守卫式 bind_session（有/无 workspace、client 有/无 bind_session）。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from auto_designer.loop.sim_user import make_sim_run_session_fn
from auto_designer.models import Persona, SeedScenario, Session, WorkspaceSpec
from auto_designer.tracker.fake import FakeTracker
from auto_designer.user.session_store import SessionStore
from auto_designer.user.sim.harness_adapter import ScriptedHarness
from auto_designer.user.sim.run_live import expert
from auto_designer.user.sim.workspace import materialize


# --------------------------------------------------------------------------
# materialize
# --------------------------------------------------------------------------
def test_materialize_creates_runnable_copy() -> None:
    ws = materialize(WorkspaceSpec(fixture="billing-split"))
    root = Path(ws)
    assert root.is_dir()
    assert (root / "billing" / "core.py").is_file()

    # 可被 python 直接执行（stdlib-only）
    run = subprocess.run(
        [sys.executable, "billing/core.py"], cwd=ws, capture_output=True, text=True
    )
    assert run.returncode == 0, run.stderr

    # 可被 import 并调用基线里已有的小工具
    imp = subprocess.run(
        [sys.executable, "-c", "import billing.core as c; print(c.format_amount(1234))"],
        cwd=ws,
        capture_output=True,
        text=True,
    )
    assert imp.returncode == 0, imp.stderr
    assert "12.34" in imp.stdout
    # 基线故意不含解法实现（split_bill 是会话里要新增并核实的目标，不得预置）
    assert "def split_bill" not in (root / "billing" / "core.py").read_text()


def test_materialize_is_isolated() -> None:
    spec = WorkspaceSpec(fixture="billing-split")
    a, b = materialize(spec), materialize(spec)
    assert a != b
    (Path(a) / "billing" / "core.py").write_text("# clobbered\n")
    assert "clobbered" not in (Path(b) / "billing" / "core.py").read_text()


def test_materialize_delegates_to_provision() -> None:
    # spec-0009/T1：materialize 退化为 SeedSource 注册表 provision 的兼容壳。
    from auto_designer.user.sim.seed_source import provision

    spec = WorkspaceSpec(fixture="billing-split")
    m, p = materialize(spec), provision(spec)
    assert m != p  # 各自独立隔离
    assert (Path(m) / "billing" / "core.py").is_file()
    assert (Path(p) / "billing" / "core.py").is_file()


# --------------------------------------------------------------------------
# 序列化 / 向后兼容
# --------------------------------------------------------------------------
def test_workspace_spec_defaults_and_roundtrip() -> None:
    spec = WorkspaceSpec(fixture="billing-split")
    assert spec.setup == []  # 默认空，本轮不执行
    assert WorkspaceSpec.from_dict(spec.to_dict()) == spec


def test_seed_scenario_backward_compatible() -> None:
    s = SeedScenario(description="x")
    assert s.workspace is None
    assert s.to_dict() == {"description": "x"}  # 旧场景序列化形状不变
    assert SeedScenario.from_dict({"description": "x"}) == s

    s2 = SeedScenario(description="y", workspace=WorkspaceSpec(fixture="billing-split"))
    assert SeedScenario.from_dict(s2.to_dict()) == s2


# --------------------------------------------------------------------------
# sim_user 桥接：守卫式 bind_session
# --------------------------------------------------------------------------
def _model_persona(sp) -> Persona:
    return Persona(
        identity=sp.persona_id, level=sp.d1.value, domain="x", goal="g", speaking_style="s"
    )


class _RecordingClient:
    """暴露 bind_session 的内层 client 替身，并能驱动 loop 跑完。"""

    def __init__(self) -> None:
        self.bound: tuple | None = None
        self.bindings = []

    def bind_session(self, persona, workspace_dir):
        self.bound = (persona, workspace_dir)
        self.bindings.append(self.bound)

    def respond(self, system: str, user: str) -> dict:
        if "<rate_experience>" in user:
            return {"score": 4, "reason": "great"}
        if "<file_issue>" in user:
            return {"issue": "n/a"}
        if "<main_judge>" in user or "<main_judge_intent>" in user:
            return {
                "perceive": "",
                "verdict": "satisfied",
                "intent": "accept",
                "task_load": "normal",
            }
        if "<main_intent>" in user:
            return {"intent": "accept and move on"}
        return {
            "perceive": "",
            "verdict": "satisfied",
            "intent": "accept",
            "action": "accept",
            "message": "ok",
            "gap": False,
        }


def _make_fn(client, tmp_path, sp, mp):
    return make_sim_run_session_fn(
        client_factory=lambda: client,  # Spec-0017/T2：工厂注入；本测试关心 bind，恒返同一实例即可
        tracker=FakeTracker(),
        store=SessionStore(tmp_path),
        sim_personas={mp.identity: sp},
    )


def test_bridge_binds_when_workspace_present(tmp_path) -> None:
    sp, client = expert(), _RecordingClient()
    mp = _model_persona(sp)
    fn = _make_fn(client, tmp_path, sp, mp)
    scenario = SeedScenario(description="task", workspace=WorkspaceSpec(fixture="billing-split"))
    fn(mp, scenario, ScriptedHarness())

    assert client.bound is not None
    persona, ws = client.bindings[0]
    assert persona is sp
    assert ws.cwd.endswith("billing-split")
    assert client.bound[1].runtime_id == "review-snapshot"


def test_bridge_without_workspace_binds_only_an_empty_terminal_snapshot(tmp_path) -> None:
    sp, client = expert(), _RecordingClient()
    mp = _model_persona(sp)
    fn = _make_fn(client, tmp_path, sp, mp)
    fn(mp, SeedScenario(description="task"), ScriptedHarness())
    assert len(client.bindings) == 1
    assert client.bound[1].runtime_id == "review-snapshot"
    assert client.bound[1].evidence["omissions"] == ["no_workspace"]


def test_bridge_no_error_when_client_lacks_bind(tmp_path) -> None:
    sp = expert()
    mp = _model_persona(sp)

    class _Plain:
        def respond(self, system: str, user: str) -> dict:
            if "<rate_experience>" in user:
                return {"score": 4, "reason": "ok"}
            if "<main_judge>" in user or "<main_judge_intent>" in user:
                return {
                    "perceive": "",
                    "verdict": "satisfied",
                    "intent": "accept",
                    "task_load": "normal",
                }
            if "<main_intent>" in user:
                return {"intent": "accept"}
            return {
                "perceive": "",
                "verdict": "satisfied",
                "action": "accept",
                "message": "ok",
                "gap": False,
            }

    fn = _make_fn(_Plain(), tmp_path, sp, mp)
    scenario = SeedScenario(description="task", workspace=WorkspaceSpec(fixture="billing-split"))
    session = fn(mp, scenario, ScriptedHarness())  # materialize 发生但无 bind，不应报错
    assert isinstance(session, Session)


# Spec-0008/T1 v2：orchestrator 传入共享 workspace_dir 时，sim_user 复用它绑定、不再自行 materialize。
def test_bridge_uses_passed_workspace_dir_and_skips_materialize(tmp_path, monkeypatch) -> None:
    sp, client = expert(), _RecordingClient()
    mp = _model_persona(sp)
    monkeypatch.setattr(  # 传入 workspace_dir 后绝不该再 materialize
        "auto_designer.loop.sim_user.materialize_workspace",
        lambda spec: (_ for _ in ()).throw(AssertionError("不应 materialize")),
    )
    fn = _make_fn(client, tmp_path, sp, mp)
    scenario = SeedScenario(description="task", workspace=WorkspaceSpec(fixture="billing-split"))
    fn(mp, scenario, ScriptedHarness(), workspace_dir="/shared/ws")

    assert client.bound[0] is sp
    assert client.bindings[0][1].cwd == "/shared/ws"
    assert client.bound[1].runtime_id == "review-snapshot"

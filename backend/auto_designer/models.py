"""用户侧最小链路的公共数据结构（spec-0001/T1）。

全部为纯数据 dataclass，无行为，可双向 dict 序列化（to_dict / from_dict）。
体感与 Session 落本地 data/sessions/（T6）；issue 不落本地，经 IssueTracker 提交至 Gitea，
本地只持 IssueRef 回执（T5）。Session.sim_trace 可选承载 god-view（决策时间线+心路）。
轻量不变量在 __post_init__ 断言，不引入外部校验器。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# 合法的对话角色集合（Transcript 每轮 role 必属其一）。
_ROLES = ("user", "harness")
# 合法的 issue 状态集合（与 Gitea state 语义对齐）。
ISSUE_STATES = ("open", "closed")


@dataclass
class Persona:
    """用户画像（给定输入）：身份/水平/领域/目标/说话风格。来源归后续 distill spec。"""

    identity: str
    level: str
    domain: str
    goal: str
    speaking_style: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity,
            "level": self.level,
            "domain": self.domain,
            "goal": self.goal,
            "speaking_style": self.speaking_style,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Persona:
        return cls(
            identity=data["identity"],
            level=data["level"],
            domain=data["domain"],
            goal=data["goal"],
            speaking_style=data["speaking_style"],
        )


@dataclass
class WorkspaceSpec:
    """种子工作区规格：经可插拔 SeedSource（按 kind 分派）落地一个隔离工作区目录。

    spec-0009/T1：`kind` 选择供给实现（缺省 `local-fixture`，= 0008 行为）；`params` 为
    source 专属入参的通用载体（如 empty 源的 doc/doc_name），使新增源不必扩 WorkspaceSpec。
    `fixture` 为 local-fixture 源使用的 backend/seed_workspaces/<fixture>/ 目录名；
    `setup` 为命令钩子；由 spec-0009/T3 的 `ensure_deps` 在 materialize 后执行（约定建
    per-workspace `.venv` + pip 装入依赖）。与 benchmark held-out 红线无关——工作区不含 gold 测试。
    """

    fixture: str = ""
    kind: str = "local-fixture"
    params: dict[str, Any] = field(default_factory=dict)
    setup: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        # 默认 kind/空 params 不落键，保持 0008 既有序列化形状（向后兼容）。
        d: dict[str, Any] = {"fixture": self.fixture, "setup": list(self.setup)}
        if self.kind != "local-fixture":
            d["kind"] = self.kind
        if self.params:
            d["params"] = dict(self.params)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkspaceSpec:
        return cls(
            fixture=data.get("fixture", ""),
            kind=data.get("kind", "local-fixture"),
            params=dict(data.get("params", {})),
            setup=list(data.get("setup", [])),
        )


@dataclass
class SeedScenario:
    """种子场景（给定输入）：一局会话的初始诉求/任务描述（非测试用例）。

    workspace 可选：非空时携带一个基线项目工作区（spec-0008/T1），供内层 tool-using
    用户 agent 在自有 sandbox 真执行核实；为 None 时退化为今天的纯文本场景。
    """

    description: str
    workspace: WorkspaceSpec | None = None

    def to_dict(self) -> dict[str, Any]:
        # workspace=None 时不落该键，保持既有纯文本场景的序列化形状不变（向后兼容）。
        d: dict[str, Any] = {"description": self.description}
        if self.workspace is not None:
            d["workspace"] = self.workspace.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SeedScenario:
        ws = data.get("workspace")
        return cls(
            description=data["description"],
            workspace=WorkspaceSpec.from_dict(ws) if ws else None,
        )


@dataclass
class Turn:
    """对话一轮：role ∈ {user, harness} 与 content。Transcript 的组成单元。

    steps：仅 harness 轮可选携带——该轮 harness 内层迭代的过程流（{kind,text} 序列，
    assistant 发言 / 工具调用 / 结果）。content 是给用户看的最终答案；steps 是观测层展开时才看的
    完整内层过程（persona 只吃 content，不吃 steps）。默认空，非空才进 to_dict（不改既有序列化形状）。
    """

    role: str
    content: str
    steps: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        assert self.role in _ROLES, f"非法 role：{self.role!r}（须属 {_ROLES}）"

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.steps:
            d["steps"] = self.steps
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Turn:
        return cls(role=data["role"], content=data["content"], steps=data.get("steps", []))


@dataclass
class Transcript:
    """有序多轮对话记录（过程产物）。每轮 role ∈ {user, harness}，构造期校验。"""

    turns: list[Turn] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"turns": [t.to_dict() for t in self.turns]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Transcript:
        return cls(turns=[Turn.from_dict(t) for t in data.get("turns", [])])


@dataclass
class FeelingScore:
    """1–4 体感评分 + 理由（会话末产出，作训练信号）。越界即构造期失败。"""

    score: int
    reason: str

    def __post_init__(self) -> None:
        assert 1 <= self.score <= 4, f"体感分越界：{self.score}（须在 1..4）"

    def to_dict(self) -> dict[str, Any]:
        return {"score": self.score, "reason": self.reason}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FeelingScore:
        return cls(score=data["score"], reason=data["reason"])


@dataclass
class PersonaCallTrace:
    """用户 agent 单次 LLM 调用的原始痕迹（先全量落盘，后续再筛）。

    system/user 保留完整原文，便于事后看 KV 复用（重复多 → 提示词未优化）。
    raw = 模型原文；parsed = 解析后的合同 JSON；steps = Agentic 内层 tool 过程流。
    """

    role: str
    system: str
    user: str
    raw: str
    parsed: dict[str, Any] = field(default_factory=dict)
    steps: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "role": self.role,
            "system": self.system,
            "user": self.user,
            "raw": self.raw,
            "parsed": dict(self.parsed),
        }
        if self.steps:
            d["steps"] = list(self.steps)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PersonaCallTrace:
        return cls(
            role=data.get("role", ""),
            system=data.get("system", ""),
            user=data.get("user", ""),
            raw=data.get("raw", ""),
            parsed=dict(data.get("parsed") or {}),
            steps=list(data.get("steps") or []),
        )


@dataclass
class SimTurn:
    """sim 上帝视角一轮：对话片段 + 心路同条共置（对齐 user.sim.loop.TurnLog）。

    与 Transcript 不是 1:1——一条 SimTurn = 一次 persona 决策（含 waiting 心跳、silent 自观察），
    message / harness_output 是该决策时刻的对话片段，perceive / verdict / action 是心路。
    persona_trace：该决策触发的用户 agent LLM 原始调用（含 system/user，供 KV 复用分析）。
    Spec-0024/T6：utterance_id / delivery / queued_behind / answers_* 做请求–回复显式配对。
    """

    turn: int
    phase: str
    action_space: list[Any]
    perceive: str
    verdict: str
    action: str
    message: str
    executor: str
    channel: str
    patience: int
    trust: str
    harness_output: str = ""
    harness_steps: list[dict[str, Any]] = field(default_factory=list)
    harness_events: list[dict[str, Any]] = field(default_factory=list)
    persona_trace: list[PersonaCallTrace] = field(default_factory=list)
    utterance_id: str = ""
    delivery: str = ""
    queued_behind: str = ""
    answers_utterance_id: str = ""
    answers_said: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "turn": self.turn,
            "phase": self.phase,
            "action_space": list(self.action_space),
            "perceive": self.perceive,
            "verdict": self.verdict,
            "action": self.action,
            "message": self.message,
            "executor": self.executor,
            "channel": self.channel,
            "patience": self.patience,
            "trust": self.trust,
            "harness_output": self.harness_output,
        }
        if self.harness_steps:
            d["harness_steps"] = list(self.harness_steps)
        if self.harness_events:
            d["harness_events"] = list(self.harness_events)
        if self.persona_trace:
            d["persona_trace"] = [c.to_dict() for c in self.persona_trace]
        # Spec-0024/T6：缺省空串不落键，旧 JSON 兼容
        if self.utterance_id:
            d["utterance_id"] = self.utterance_id
        if self.delivery:
            d["delivery"] = self.delivery
        if self.queued_behind:
            d["queued_behind"] = self.queued_behind
        if self.answers_utterance_id:
            d["answers_utterance_id"] = self.answers_utterance_id
        if self.answers_said:
            d["answers_said"] = self.answers_said
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SimTurn:
        return cls(
            turn=data["turn"],
            phase=data["phase"],
            action_space=list(data.get("action_space", [])),
            perceive=data.get("perceive", ""),
            verdict=data.get("verdict", ""),
            action=data.get("action", ""),
            message=data.get("message", ""),
            executor=data.get("executor", ""),
            channel=data.get("channel", ""),
            patience=int(data.get("patience", 0)),
            trust=data.get("trust", ""),
            harness_output=data.get("harness_output", ""),
            harness_steps=list(data.get("harness_steps", [])),
            harness_events=list(data.get("harness_events", [])),
            persona_trace=[PersonaCallTrace.from_dict(c) for c in data.get("persona_trace", [])],
            utterance_id=str(data.get("utterance_id") or ""),
            delivery=str(data.get("delivery") or ""),
            queued_behind=str(data.get("queued_behind") or ""),
            answers_utterance_id=str(data.get("answers_utterance_id") or ""),
            answers_said=str(data.get("answers_said") or ""),
        )


@dataclass
class SimTrace:
    """一局会话的完整 god-view（SessionResult 可持久化投影）。

    transcript 仍是对话投影（看板/聚合用）；sim_trace 是决策时间线权威源。
    persona_tail：局末不挂在某一 Turn 上的调用（file_issue 正文 / 体感评分）。
    旧 session 无此字段 → None。
    """

    persona_id: str
    end_reason: str
    turns: list[SimTurn] = field(default_factory=list)
    signals: list[str] = field(default_factory=list)
    feeling_derived: FeelingScore | None = None
    persona_tail: list[PersonaCallTrace] = field(default_factory=list)
    # valid | invalid。invalid 表示用户评估器自身协议/解析失败，不是 harness 任务失败。
    evaluation_status: str = "valid"
    evaluation_error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "persona_id": self.persona_id,
            "end_reason": self.end_reason,
            "turns": [t.to_dict() for t in self.turns],
            "signals": list(self.signals),
        }
        if self.feeling_derived is not None:
            d["feeling_derived"] = self.feeling_derived.to_dict()
        if self.persona_tail:
            d["persona_tail"] = [c.to_dict() for c in self.persona_tail]
        if self.evaluation_status != "valid":
            d["evaluation_status"] = self.evaluation_status
        if self.evaluation_error is not None:
            d["evaluation_error"] = dict(self.evaluation_error)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SimTrace:
        fd = data.get("feeling_derived")
        return cls(
            persona_id=data["persona_id"],
            end_reason=data["end_reason"],
            turns=[SimTurn.from_dict(t) for t in data.get("turns", [])],
            signals=list(data.get("signals", [])),
            feeling_derived=FeelingScore.from_dict(fd) if fd else None,
            persona_tail=[PersonaCallTrace.from_dict(c) for c in data.get("persona_tail", [])],
            evaluation_status=str(data.get("evaluation_status") or "valid"),
            evaluation_error=(
                dict(data["evaluation_error"])
                if isinstance(data.get("evaluation_error"), dict)
                else None
            ),
        )


@dataclass
class IssueDraft:
    """用户 agent 产出的问题草稿（title/body/labels），一局 0..n 条。对齐 Gitea 建 issue 入参。"""

    title: str
    body: str
    labels: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"title": self.title, "body": self.body, "labels": list(self.labels)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IssueDraft:
        return cls(
            title=data["title"],
            body=data["body"],
            labels=list(data.get("labels", [])),
        )


@dataclass
class OpenIssue:
    """从 tracker 读回的一条 issue（number/title/body/labels/state）。

    用于开发者侧领取 issue（spec-0003/T3）：IssueTracker 的写路径产 IssueRef，读路径(list_open_issues)产 OpenIssue。
    """

    number: int
    title: str
    body: str
    labels: list[str] = field(default_factory=list)
    state: str = "open"

    def to_dict(self) -> dict[str, Any]:
        return {
            "number": self.number,
            "title": self.title,
            "body": self.body,
            "labels": list(self.labels),
            "state": self.state,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> OpenIssue:
        return cls(
            number=data["number"],
            title=data["title"],
            body=data["body"],
            labels=list(data.get("labels", [])),
            state=data.get("state", "open"),
        )


@dataclass
class IssueRef:
    """issue 提交至 Gitea 后的回执（number/url/state）；本地只持回执，权威源在 Gitea。"""

    number: int
    url: str
    state: str

    def to_dict(self) -> dict[str, Any]:
        return {"number": self.number, "url": self.url, "state": self.state}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> IssueRef:
        return cls(number=data["number"], url=data["url"], state=data["state"])


@dataclass
class Session:
    """一局会话的完整封装：聚合 persona/scenario/transcript/feeling/issue_refs，自带 id 与时间。

    session_id 与 created_at 缺省自动生成（T4 构造时不必显式传），to_dict/from_dict 保真。
    sim_trace：可选 god-view（决策时间线）；缺省 None，旧 JSON 无该键兼容。
    """

    persona: Persona
    scenario: SeedScenario
    transcript: Transcript
    feeling: FeelingScore
    issue_refs: list[IssueRef] = field(default_factory=list)
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: datetime = field(default_factory=datetime.now)
    sim_trace: SimTrace | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat(),
            "persona": self.persona.to_dict(),
            "scenario": self.scenario.to_dict(),
            "transcript": self.transcript.to_dict(),
            "feeling": self.feeling.to_dict(),
            "issue_refs": [r.to_dict() for r in self.issue_refs],
        }
        if self.sim_trace is not None:
            d["sim_trace"] = self.sim_trace.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Session:
        st = data.get("sim_trace")
        return cls(
            persona=Persona.from_dict(data["persona"]),
            scenario=SeedScenario.from_dict(data["scenario"]),
            transcript=Transcript.from_dict(data["transcript"]),
            feeling=FeelingScore.from_dict(data["feeling"]),
            issue_refs=[IssueRef.from_dict(r) for r in data.get("issue_refs", [])],
            session_id=data["session_id"],
            created_at=datetime.fromisoformat(data["created_at"]),
            sim_trace=SimTrace.from_dict(st) if st else None,
        )

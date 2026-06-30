"""用户侧最小链路的公共数据结构（spec-0001/T1）。

全部为纯数据 dataclass，无行为，可双向 dict 序列化（to_dict / from_dict）。
体感与 Session 落本地 data/sessions/（T6）；issue 不落本地，经 IssueTracker 提交至 Gitea，
本地只持 IssueRef 回执（T5）。轻量不变量在 __post_init__ 断言，不引入外部校验器。
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
    `setup` 为命令钩子（占位，本轮不执行）。与 benchmark held-out 红线无关——工作区不含 gold 测试。
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
    """对话一轮：role ∈ {user, harness} 与 content。Transcript 的组成单元。"""

    role: str
    content: str

    def __post_init__(self) -> None:
        assert self.role in _ROLES, f"非法 role：{self.role!r}（须属 {_ROLES}）"

    def to_dict(self) -> dict[str, Any]:
        return {"role": self.role, "content": self.content}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Turn:
        return cls(role=data["role"], content=data["content"])


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
    """

    persona: Persona
    scenario: SeedScenario
    transcript: Transcript
    feeling: FeelingScore
    issue_refs: list[IssueRef] = field(default_factory=list)
    session_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat(),
            "persona": self.persona.to_dict(),
            "scenario": self.scenario.to_dict(),
            "transcript": self.transcript.to_dict(),
            "feeling": self.feeling.to_dict(),
            "issue_refs": [r.to_dict() for r in self.issue_refs],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Session:
        return cls(
            persona=Persona.from_dict(data["persona"]),
            scenario=SeedScenario.from_dict(data["scenario"]),
            transcript=Transcript.from_dict(data["transcript"]),
            feeling=FeelingScore.from_dict(data["feeling"]),
            issue_refs=[IssueRef.from_dict(r) for r in data.get("issue_refs", [])],
            session_id=data["session_id"],
            created_at=datetime.fromisoformat(data["created_at"]),
        )

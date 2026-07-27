# divergent PM：与 synthesize 并行，从交互挖产品候选（不可领）；经 gate 晋升后才进 dev。
"""Divergent PM 驱动器：同构 synthesize 信号，产出带 `divergent` 标签的候选 issue。

候选 **不进** 可领 backlog（无 triaged/RFC）。同一轮末由 Designer.gate_once 做语义晋升评审
（promote → feature+triaged；hold → 保持；drop → 关闭）。
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from auto_designer.designer.designer import (
    _DESIGN_TIMEOUT,
    _Proposal,
    _run_with_timeout,
    _unwrap_result,
)
from auto_designer.designer.issue_schema import DIVERGENT, round_label
from auto_designer.designer.issue_schema import fields_of as _schema_fields_of
from auto_designer.designer.issue_schema import render as _schema_render
from auto_designer.designer.issue_schema import validate as _schema_validate
from auto_designer.designer.runtime_agg import aggregate_runtime, format_runtime_agg
from auto_designer.designer.session_timeline import bind_session_store
from auto_designer.models import IssueDraft
from auto_designer.tracker.base import IssueTracker
from auto_designer.user.session_store import SessionStore

# 每轮硬顶，防灌单（gate 再做跨轮去重/晋升）。
_MAX_CANDIDATES = 3

StatusFn = Callable[..., None]


@dataclass
class DivergentOutcome:
    """一次 propose_once：新落的候选票号。"""

    proposal_numbers: list[int] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.proposal_numbers)


class Divergent:
    """发散 PM：产 divergent 候选，不碰 git、不改 harness 文件。"""

    def __init__(
        self,
        tracker: IssueTracker,
        store: SessionStore,
        harness_repo: str,
        agent_def_dir: str,
        on_status: StatusFn | None = None,
        on_event: Callable[[str, str], None] | None = None,
        round_provider: Callable[[], int | None] | None = None,
    ) -> None:
        self._tracker = tracker
        self._store = store
        self._repo = Path(harness_repo)
        self._agent_def = Path(agent_def_dir)
        self._on_status = on_status
        self._on_event = on_event
        self._round_provider = round_provider

    def propose_once(self) -> DivergentOutcome:
        backlog = self._tracker.list_open_issues()
        # 给模型看的「已 groomed」与 synthesize 一致；另附当前仍 open 的 divergent 候选（跨轮积压）。
        from auto_designer.designer.issue_schema import RFC_LABEL, SUPERSEDED, TRIAGED

        triaged = [
            i
            for i in backlog
            if TRIAGED in i.labels and RFC_LABEL not in i.labels and SUPERSEDED not in i.labels
        ]
        pending = [i for i in backlog if DIVERGENT in i.labels]
        rfcs = [i for i in backlog if RFC_LABEL in i.labels]
        trend = self._feeling_trend()
        runtime = format_runtime_agg(aggregate_runtime(store=self._store, harness_repo=self._repo))
        self._emit(
            running=True,
            status=f"发散中…（triaged={len(triaged)} · 积压候选={len(pending)}）",
        )

        result_text = self._run_agent(
            triaged=triaged,
            pending=pending,
            rfcs=rfcs,
            trend=trend,
            runtime=runtime,
        )
        proposals = self._parse_proposals(result_text)[:_MAX_CANDIDATES]

        numbers: list[int] = []
        if proposals:
            self._tracker.ensure_labels([DIVERGENT])
        round_no = self._round_provider() if self._round_provider is not None else None
        for prop in proposals:
            fields = _rfc_fields_by_label(prop.fields)
            if _schema_validate(kind="rfc", fields=fields, section="triage"):
                continue
            body = _schema_render(kind="rfc", fields=fields)
            labels = [DIVERGENT]
            if isinstance(round_no, int) and round_no > 0:
                labels.append(round_label(round_no))
            ref = self._tracker.create_issue(
                IssueDraft(title=str(prop.title), body=body, labels=labels)
            )
            numbers.append(ref.number)

        self._emit(
            running=False,
            status=(f"落了 {len(numbers)} 条 divergent 候选" if numbers else "本轮无产品候选"),
            proposals=numbers,
            detail=(result_text or None),
        )
        return DivergentOutcome(proposal_numbers=numbers)

    def _run_agent(
        self,
        *,
        triaged: list,
        pending: list,
        rfcs: list,
        trend: list[tuple[str, int, str, str]],
        runtime: str,
    ) -> str:
        os.environ["SANDBOX_WORK_DIR"] = str(self._repo.resolve())
        from nexau import Agent, AgentConfig  # noqa: PLC0415

        cfg = AgentConfig.from_yaml(config_path=self._agent_def / "agent.yaml")
        if self._on_event is not None:
            from auto_designer.loop.live_tracer import StepTracer  # noqa: PLC0415

            cfg.resolved_tracer = StepTracer(self._on_event)
        agent = Agent(config=cfg)
        rfc_labels = "/".join(f.label for f in _schema_fields_of(kind="rfc"))
        msg = (
            "下面是与 synthesize **同一份**信号。你是 divergent PM：挖用户可感知的产品机会；"
            f"本轮最多提 {_MAX_CANDIDATES} 条**增量**候选（相对已积压 divergent / 已有 RFC 勿重复）。\n"
            "先按需读 MANUAL / 时间线核对，再用 complete_task 交 JSON 数组。\n\n"
            f"## 已 triaged backlog（{len(triaged)} 条）\n{self._format_issues(triaged)}\n\n"
            f"## 已 open RFC（{len(rfcs)} 条，勿再提同施力点）\n{self._format_issues(rfcs)}\n\n"
            f"## 仍 open 的 divergent 候选（{len(pending)} 条，跨轮积压；勿换皮重复）\n"
            f"{self._format_issues(pending)}\n\n"
            f"## 体感曲线\n{self._format_trend(trend)}\n\n"
            f"## 运行时行为聚合\n{runtime}\n\n"
            "对疑惑点先 `get_session_timeline`，必要时再 beat/step；勿直接读 sessions/ 文件。\n\n"
            "complete_task：result 只放 JSON 数组，每项含 `title`、"
            f"`fields`（{rfc_labels}），可选 `covers`；无则 `[]`。"
        )
        with bind_session_store(self._store):
            out = _run_with_timeout(lambda: agent.run(message=msg), _DESIGN_TIMEOUT)
        return _unwrap_result(out)

    def _feeling_trend(self) -> list[tuple[str, int, str, str]]:
        rows = sorted(self._store.index(), key=lambda e: e["created_at"])
        return [
            (
                e["created_at"],
                e["score"],
                str(e.get("reason", "")),
                str(e.get("session_id", "")),
            )
            for e in rows
        ]

    @staticmethod
    def _format_issues(issues: list) -> str:
        if not issues:
            return "（空）"
        return "\n".join(
            f"- #{i.number} [{','.join(i.labels)}] {i.title}\n  {i.body}" for i in issues
        )

    @staticmethod
    def _format_trend(trend: list[tuple[str, int, str, str]]) -> str:
        if not trend:
            return "（暂无体感数据）"
        lines = []
        for ts, score, reason, sid in trend:
            why = f" — {reason}" if reason else ""
            sid_bit = f" [session={sid}]" if sid else ""
            lines.append(f"- {ts}{sid_bit}: {score}{why}")
        return "\n".join(lines)

    @staticmethod
    def _parse_proposals(text: str) -> list[_Proposal]:
        # 复用 Designer 解析器（同 JSON 形状）。
        from auto_designer.designer.designer import Designer

        return Designer._parse_proposals(text)

    def _emit(self, *, running: bool, status: str, **kw: object) -> None:
        if self._on_status is not None:
            self._on_status(running=running, status=status, **kw)


def _norm_label(s: object) -> str:
    return "".join(str(s).split())


def _rfc_fields_by_label(fields: dict) -> dict:
    label_to_key = {_norm_label(f.label): f.key for f in _schema_fields_of(kind="rfc")}
    return {label_to_key.get(_norm_label(k), str(k)): v for k, v in fields.items()}

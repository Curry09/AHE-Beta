# Spec-0029/T6：Owner = 唯一准入——每轮一次批量裁决 proposal → ready/merged/declined/hold。
"""Owner 驱动器：三平面模型的唯一准入口（backlog grooming / Definition of Ready 的执行者）。

生成器（triage/synthesize/divergent）产的提案一律不可领；进 ready 与否、重复合并、覆盖裁决、
终优先级——全部集中在此（生成侧因此解耦、可自由并行）。每轮一次 `admit_once()`，两级裁决：

- **机械段（零 LLM）**：from-triage 的单条修复案（字段已在 triage 升级时校验过）、与既有 ready/
  本批其它提案**无标题近似冲突** → 自动 admit。拿不准（有冲突嫌疑）就进评审段——宁审勿误放。
- **评审段（一次批量 LLM）**：其余（结构/产品提案、冲突组）走 owner agent，`submit_admission`
  收尾（nexau 工具层强校验）。

决策落库（裁决优先级 = **显式决策 > covers 默认 merge > 全局默认 hold**）：
- admit   → 去 proposal 加 `openagents` 交付面交接令牌（+终优先级，可覆盖 triage 建议值）；
  vigil 发现后自己盖 ready 并排依赖边（Spec-0032/T3，plane 读侧两标签同属 READY 平面）。
- merge   → 关闭 + `merged-into: #主票` 机器行（重复归并的唯一落点）。
- decline → declined + 原因 + 关闭。
- hold    → 保持 proposal，下轮再审（未列出的提案默认 hold）。
- **covers 级联的唯一落点**：显式决策应用完后，对每条已 admit 的提案（按票号序确定性处理），
  将其 covers 里仍 open、未被本批显式裁决的 report/proposal 票默认 merge 到它；结构案被 hold/
  decline 则 covers 不触发任何级联。dev 完成时不再级联（_close_covered 已退役）。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

from auto_designer.designer.agent_runtime import norm_label, read_submit, run_agent_def
from auto_designer.designer.issue_schema import (
    DECLINED,
    FROM_TRIAGE,
    MERGED,
    NEEDS_TRIAGE,
    OPENAGENTS,
    PRIORITIES,
    PROPOSAL,
    READY,
    REPORT,
    TRIAGED,
    format_merged_into,
    parse_covers_line,
    plane,
    priority_of,
    provenance_of,
)
from auto_designer.tracker.base import IssueTracker
from auto_designer.user.session_store import SessionStore

_ADMIT_TIMEOUT = 1800
# 机械段冲突判定的标题相似度阈值（norm 后 SequenceMatcher ratio）。保守取低值：宁进评审勿误放行。
_TITLE_CONFLICT_RATIO = 0.6

StatusFn = Callable[..., None]


@dataclass
class AdmitOutcome:
    """一次 admit_once 的结果：各裁决命中的票号。"""

    admitted: list[int] = field(default_factory=list)
    merged: list[int] = field(default_factory=list)
    declined: list[int] = field(default_factory=list)
    held: list[int] = field(default_factory=list)
    mechanical: list[int] = field(default_factory=list)  # admitted 的子集：机械段零 LLM 放行的


def _ready_labels(current: list[str], priority: str | None) -> list[str]:
    """admit：去平面/旧工作流标签，加 `openagents` 交接令牌；priority 合法时替换旧 P*（终优先级）。

    Spec-0032/T3：Owner 准入不再直接打 ready——`openagents` 是交付面（vigil）的发现标签，vigil
    `_intake` 发现后自己盖 ready 并触发 curator 依赖排序；Owner 直打 ready 会让 vigil 跳过该票、
    curator 永不运行（准入语义不变：plane() 把两标签同视为 READY 平面）。
    """
    drop = {PROPOSAL, REPORT, NEEDS_TRIAGE, TRIAGED}
    keep = [x for x in current if x not in drop]
    if priority in PRIORITIES:
        keep = [x for x in keep if x not in PRIORITIES]
        keep.append(priority)
    return list(dict.fromkeys([*keep, OPENAGENTS]))


def _terminal_labels(current: list[str], terminal: str) -> list[str]:
    """merge/decline：去平面标签（含交付面令牌），加终态标签。"""
    drop = {PROPOSAL, REPORT, NEEDS_TRIAGE, TRIAGED, READY, OPENAGENTS}
    keep = [x for x in current if x not in drop]
    return list(dict.fromkeys([*keep, terminal]))


def _titles_conflict(a: str, b: str) -> bool:
    """标题近似判定（机械段冲突检测）：norm 后 SequenceMatcher ratio ≥ 阈值。"""
    na, nb = norm_label(a), norm_label(b)
    if not na or not nb:
        return False
    return SequenceMatcher(None, na, nb).ratio() >= _TITLE_CONFLICT_RATIO


class Owner:
    """准入评审驱动器：机械 + 评审双模式批量裁决。恒 1 实例（全局视野的单点）。"""

    def __init__(
        self,
        tracker: IssueTracker,
        store: SessionStore,
        harness_repo: str,
        agent_def_dir: str,
        on_status: StatusFn | None = None,
        on_event: Callable[[str, str], None] | None = None,
        review: bool = True,
    ) -> None:
        self._tracker = tracker
        self._store = store
        self._repo = Path(harness_repo)
        self._agent_def = Path(agent_def_dir)
        self._on_status = on_status
        self._on_event = on_event
        # review=False = 纯机械准入（roster owner=0 的降级模式）：评审段跳过、其余提案 hold。
        self._review = review

    def admit_once(self) -> AdmitOutcome:
        backlog = self._tracker.list_open_issues()
        proposals = [i for i in backlog if plane(i.labels) == PROPOSAL]
        if not proposals:
            self._emit(running=False, status="无待准入提案")
            return AdmitOutcome()
        ready = [i for i in backlog if plane(i.labels) == READY]
        self._emit(running=True, status=f"准入评审中…（{len(proposals)} 条提案）")

        outcome = AdmitOutcome()
        by_number = {i.number: i for i in backlog}

        # ---- 机械段（零 LLM）：from-triage 单条案 + 无标题近似冲突 → 自动 admit ----
        mechanical, review_needed = self._split_mechanical(proposals=proposals, ready=ready)
        for issue in mechanical:
            self._admit(issue, priority=None, note="admission: 机械准入（单条修复案、无冲突）")
            outcome.admitted.append(issue.number)
            outcome.mechanical.append(issue.number)

        # ---- 评审段（一次批量 LLM）：结构/产品提案、冲突组 ----
        decisions: list[dict] = []
        if review_needed and self._review:
            result_text = self._run_agent(
                proposals=review_needed, ready=ready, trend=self._feeling_trend()
            )
            decisions = read_submit(result_text, "decisions") or []
        # review=False 或 agent 未 submit：review_needed 全部默认 hold（提案留存下轮再审）。

        reviewable = {i.number for i in review_needed}
        explicit: dict[int, dict] = {}
        for d in decisions:
            try:
                num = int(d.get("issue"))
            except (TypeError, ValueError):
                continue
            if num in reviewable and num not in explicit:  # 只裁本批评审集合；重复决策先者得
                explicit[num] = d

        # pass 1：显式决策
        for num, d in explicit.items():
            issue = by_number[num]
            decision = str(d.get("decision", "")).strip()
            try:
                if decision == "admit":
                    prio = str(d.get("priority", "")).strip().upper() or None
                    self._admit(issue, priority=prio, note="admission: admit")
                    outcome.admitted.append(num)
                elif decision == "merge":
                    into = d.get("into")
                    target = by_number.get(into) if isinstance(into, int) else None
                    if target is None or target.number == num:
                        outcome.held.append(num)  # into 非法 → hold（不瞎并）
                        continue
                    self._merge(issue, into=target.number)
                    outcome.merged.append(num)
                elif decision == "decline":
                    self._decline(issue, reason=str(d.get("reason", "")).strip())
                    outcome.declined.append(num)
                else:  # hold 或未知
                    outcome.held.append(num)
            except Exception:  # noqa: BLE001  单条落库失败不拖垮其余
                pass

        # pass 2：covers 默认级联（唯一落点）——对每条已 admit 的提案按票号序确定性处理。
        decided = set(explicit) | {i.number for i in mechanical}
        for num in sorted(outcome.admitted):
            admitted_issue = by_number.get(num)
            if admitted_issue is None:
                continue
            for n in parse_covers_line(admitted_issue.body):
                t = by_number.get(n)
                if t is None or t.number == num or t.number in decided:
                    continue
                if plane(t.labels) not in (REPORT, PROPOSAL):
                    continue  # ready/终态不动
                try:
                    self._merge(t, into=num)
                    outcome.merged.append(t.number)
                    decided.add(t.number)
                except Exception:  # noqa: BLE001
                    pass

        # pass 3：其余评审集合默认 hold（不落库动作，只计数）
        for i in review_needed:
            if i.number not in decided and i.number not in {
                *outcome.admitted,
                *outcome.merged,
                *outcome.declined,
                *outcome.held,
            }:
                outcome.held.append(i.number)

        self._emit(
            running=False,
            status=(
                f"准入：admit {len(outcome.admitted)}（机械 {len(outcome.mechanical)}）· "
                f"merge {len(outcome.merged)} · decline {len(outcome.declined)} · "
                f"hold {len(outcome.held)}"
            ),
            proposals=outcome.admitted,
        )
        return outcome

    def _split_mechanical(self, *, proposals: list, ready: list) -> tuple[list, list]:
        """机械段拆分：from-triage 单条案（字段已由 triage 校验）、与 ready/本批其余提案无标题
        近似冲突、且**未被本批任何提案 covers** → 机械 admit；其余（结构/产品提案、冲突嫌疑、
        被覆盖候选）→ 评审段。被 covers 的必须进评审——否则机械段抢先放行后，结构案 admit 时的
        默认级联合并就够不着它了（dev 会先修症状再被结构案覆盖）。"""
        covered_in_batch: set[int] = set()
        for p in proposals:
            covered_in_batch.update(parse_covers_line(p.body))
        mechanical: list = []
        review_needed: list = []
        for p in proposals:
            if provenance_of(p.labels) != FROM_TRIAGE or p.number in covered_in_batch:
                review_needed.append(p)
                continue
            others = [x for x in proposals if x.number != p.number] + list(ready)
            if any(_titles_conflict(p.title, o.title) for o in others):
                review_needed.append(p)  # 冲突嫌疑 → 宁审勿误放
            else:
                mechanical.append(p)
        return mechanical, review_needed

    def _admit(self, issue, *, priority: str | None, note: str) -> None:
        self._tracker.set_labels(issue.number, _ready_labels(list(issue.labels), priority))
        self._safe_comment(issue.number, note)

    def _merge(self, issue, *, into: int) -> None:
        self._tracker.set_labels(issue.number, _terminal_labels(list(issue.labels), MERGED))
        self._safe_comment(issue.number, format_merged_into(into))
        self._safe_close(issue.number, f"merged into #{into}")

    def _decline(self, issue, *, reason: str) -> None:
        self._tracker.set_labels(issue.number, _terminal_labels(list(issue.labels), DECLINED))
        self._safe_comment(issue.number, f"decline：{reason or '（未给原因）'}")
        self._safe_close(issue.number, f"decline：{reason}")

    def _run_agent(
        self, *, proposals: list, ready: list, trend: list[tuple[str, int, str, str]]
    ) -> str:
        msg = (
            "你是**准入评审（Owner）**：唯一有权把提案放进 ready 工作队列的人。逐条裁决下面的待评审"
            "提案——每条给 admit（值得开工，可给终优先级 P0-P3）/ merge（与某票同施力点，给 into=主票号）"
            "/ decline（不值得做，给 reason）/ hold（信号还薄，留下轮）。**去重合并是你的核心职责**："
            "多条提案同根因/同施力点就 merge 到最完整的那条；结构提案的 covers 行是生成器的合并建议，"
            "由你裁决（admit 结构案后，其 covers 的提案默认会被并入——若其中有急修值得独立推进，"
            "显式 admit 它即可保留）。宁 hold 勿滥 admit；decline 要给得出的理由。\n\n"
            f"## 待评审提案（{len(proposals)} 条）\n{self._format_index(proposals)}\n\n"
            f"## 已在 ready 的工作项（{len(ready)} 条，判重参照）\n{self._format_index(ready)}\n\n"
            f"## 体感曲线\n{self._format_trend(trend)}\n\n"
            "对存疑提案可 `get_session_timeline`（issue_number=… / session_id=…）核对证据，必要时 "
            "beat/step 下钻；勿直接读 sessions/ 文件。\n\n"
            "裁决完**调 `submit_admission` 一次**收尾：`decisions` 每条待评审提案一项（未列出的默认 "
            "hold）。字段/枚举由工具 input_schema 强校验。"
        )
        return run_agent_def(
            self._agent_def,
            msg,
            store=self._store,
            repo=self._repo,
            timeout=_ADMIT_TIMEOUT,
            on_event=self._on_event,
        )

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
    def _format_index(issues: list) -> str:
        """紧凑索引：号/标签/标题 + covers 行（正文不喂——存疑用 timeline 下钻，限住上下文）。"""
        if not issues:
            return "（空）"
        lines = []
        for i in issues:
            covers = parse_covers_line(i.body)
            covers_bit = f"  covers={covers}" if covers else ""
            prio = priority_of(i.labels)
            prio_bit = f" 建议{prio}" if prio else ""
            lines.append(f"- #{i.number} [{','.join(i.labels)}]{prio_bit} {i.title}{covers_bit}")
        return "\n".join(lines)

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

    def _safe_comment(self, number: int, body: str) -> None:
        try:
            self._tracker.add_comment(number, body)
        except Exception:  # noqa: BLE001
            pass

    def _safe_close(self, number: int, reason: str) -> None:
        try:
            self._tracker.set_state(number, "closed", reason)
        except Exception:  # noqa: BLE001
            pass

    def _emit(self, *, running: bool, status: str, **kw: object) -> None:
        if self._on_status is not None:
            self._on_status(running=running, status=status, **kw)

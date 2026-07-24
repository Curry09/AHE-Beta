# Spec-0025/T3：triage agent 驱动——把 raw 用户 issue 就地分类+定位+去重+驳回/needs-info。
"""Triager：issue triage / maintainer = 带只读工具的 nexau agent（对偶于 synthesize 的跨条综合）。

用户提的是 raw 反馈（用户视角症状，看不到代码、信息有限）。triage agent 逐条处理带 `needs-triage`
标签的 issue，用**三管齐下的 grounding**（用户报告 + 只读 harness 代码 + `get_session_timeline`
god-view 轨迹）给每条一个 disposition：

- accept   → 确认 kind + 填 TRIAGE 区字段（根因区域/边界/验收，经 issue_schema 校验）→ 就地增补
             （去 needs-triage、加 triaged + 确认 kind），TRIAGE 字段以 comment 挂上。
- duplicate→ 与既有 triaged issue 同根因 → 关掉、链主 issue。
- reject / needs_info → 超范围/无效 或 信息不足 → 加对应标签 + 写原因 + 关闭。

agent 出草稿（disposition JSON）、driver 落库——与 synthesize / 用户 / 开发者侧同构、解耦。
优先级不在此定（由编排层按体感+频率机制派生，Spec-0025/T6）。
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from auto_designer.designer.designer import (
    _iter_top_level_arrays,
    _norm_label,
    _run_with_timeout,
    _unwrap_result,
)
from auto_designer.designer.issue_schema import (
    NEEDS_INFO,
    NEEDS_TRIAGE,
    PRIORITIES,
    REJECTED,
    RFC_LABEL,
    SUPERSEDED,
    TRIAGED,
    USER_KINDS,
    output_contract_schema,
)
from auto_designer.designer.issue_schema import (
    fields_of as schema_fields_of,
)
from auto_designer.designer.issue_schema import (
    render as schema_render,
)
from auto_designer.designer.issue_schema import (
    validate as schema_validate,
)
from auto_designer.designer.session_timeline import bind_session_store
from auto_designer.tracker.base import IssueTracker
from auto_designer.user.session_store import SessionStore

_TRIAGE_TIMEOUT = 900
# 工作流标签中「非 type、由分诊/综合流程施加」的那些——重打 type 标签时要一并剔除。
_WORKFLOW_LABELS = frozenset(
    {NEEDS_TRIAGE, TRIAGED, REJECTED, NEEDS_INFO, RFC_LABEL, SUPERSEDED, *PRIORITIES}
)

StatusFn = Callable[..., None]


@dataclass
class TriageOutcome:
    """一次 triage_once 的结果：各 disposition 命中的 issue 号。"""

    accepted: list[int] = field(default_factory=list)
    duplicate: list[int] = field(default_factory=list)
    rejected: list[int] = field(default_factory=list)
    needs_info: list[int] = field(default_factory=list)

    @property
    def handled(self) -> int:
        return len(self.accepted) + len(self.duplicate) + len(self.rejected) + len(self.needs_info)


def _parse_dispositions(text: str) -> list[dict]:
    """从 agent result 抽 JSON 数组 → list[dict]（复用 designer 的平衡括号扫描，取最后一个顶层数组）。

    解析失败/非列表 → 空（本轮无分诊，不抛错——triage 出错不该拖垮闭环）。
    """
    if not text:
        return []
    data: object | None = None
    for chunk in _iter_top_level_arrays(text):
        try:
            parsed = json.loads(chunk)
        except (ValueError, TypeError):
            continue
        if isinstance(parsed, list):
            data = parsed
    if not isinstance(data, list):
        return []
    return [d for d in data if isinstance(d, dict)]


def _confirmed_labels(current: list[str], kind: str, priority: str | None = None) -> list[str]:
    """accept：保留 round-* 及其它非 type/非工作流标签，去旧暂定 type + needs-triage + 旧优先级，
    加确认 kind + triaged + 优先级（priority 合法时）。"""
    keep = [x for x in current if x not in USER_KINDS and x not in _WORKFLOW_LABELS]
    out = [*keep, kind, TRIAGED]
    if priority in PRIORITIES:
        out.append(priority)
    return list(dict.fromkeys(out))


def _rejected_labels(current: list[str], label: str) -> list[str]:
    """reject/needs_info：保留 type + round-*，去 needs-triage，加对应否决标签。"""
    keep = [x for x in current if x not in (NEEDS_TRIAGE, TRIAGED)]
    return list(dict.fromkeys([*keep, label]))


def _fields_by_label_to_key(kind: str, fields: dict) -> dict:
    """agent 用中文 label 填字段 → 转成 schema key（root_cause/boundary/acceptance）。未知 label 忽略。
    按归一后的 label 匹配（去空白），容忍 LLM 的空格差异，避免字段映射不上致校验误判。"""
    label_to_key = {_norm_label(f.label): f.key for f in schema_fields_of(kind=kind)}
    out: dict[str, str] = {}
    for k, v in fields.items():
        key = label_to_key.get(_norm_label(k), str(k))  # 已是 key 则原样
        out[key] = v
    return out


# ---- 对齐 LLM 常见的 schema 漂移，防御式归一 ----
# LLM 有时不照输出契约、自创「分析报告」式 schema（issue_number/status/duplicate_of/needs_info/reject、
# 字段平铺在顶层而非放进 fields）。这里能救则救：救不了（如 accept 缺 TRIAGE 字段）再按 needs_info
# 降级，至少让 issue 离开 needs-triage、结论可见，而不是第一行取 `issue` 拿 None 就把每条静默丢弃。


def _issue_num(d: dict) -> object:
    """取 issue 号：优先 `issue`，兼容 `issue_number` 别名。"""
    v = d.get("issue")
    return d.get("issue_number") if v is None else v


def _normalize_dispositions(draft_text: str, *, pending_numbers: set) -> list[dict] | None:
    """约束解码归一（Spec-0025 根治）：把 triage agent 的自由结论，经 `response_format=json_schema`
    （schema 由 issue_schema.output_contract_schema() 生成，单一真源）**强制**成 schema 合规的 disposition
    数组——解码层杜绝 triage_decision/平铺字段/乱加字段/非 P0-P3 优先级。任何异常返回 None，调用方回退
    到宽容解析 `_parse_dispositions`（不因归一失败丢整轮）。"""
    if not draft_text.strip() or not pending_numbers:
        return None
    base_url = os.getenv("DESIGNER_LLM_BASE_URL")
    api_key = os.getenv("DESIGNER_LLM_API_KEY")
    model = os.getenv("DESIGNER_LLM_MODEL")
    if not (base_url and api_key and model):
        return None
    try:
        from openai import OpenAI  # noqa: PLC0415  运行时依赖，懒加载
    except Exception:  # noqa: BLE001
        return None
    prompt = (
        "把下面的 triage 结论整理成严格符合 schema 的 dispositions（每条待分诊 issue 恰好一项）。\n"
        f"待分诊 issue 号：{sorted(pending_numbers)}。只对这些号产出，不多不少。\n"
        "**accept 的定位必须放进 fields 对象（键用该 kind 的中文 TRIAGE 字段名），每字段一句话；"
        "reason 只用于 reject/needs_info，accept 绝不用 reason。** 各 kind 的 fields 键：\n"
        '  bug → {"根因区域":"…","边界":"…","验收":"…"}\n'
        '  feature → {"边界":"…","交付物":"…","验收":"…"}\n'
        '  chore → {"边界":"…","验收":"…"}；document → {"验收":"…"}\n'
        "该 kind 列出的字段**必须全给、一个都不能少**（缺任一会被降级为 needs_info）。\n"
        "priority 只能是 P0/P1/P2/P3（按严重度×体感）。示例一条完整 accept：\n"
        '  {"issue":12,"disposition":"accept","kind":"bug","priority":"P1",'
        '"fields":{"根因区域":"entry.py 无预算感知","边界":"只改通用能力","验收":"同类任务预算内交付"}}\n'
        '  duplicate：{"issue":13,"disposition":"duplicate","of":12}\n'
        '  reject/needs_info：{"issue":14,"disposition":"needs_info","reason":"轨迹无有效信息，无法定位"}\n\n'
        f"triage 结论原文：\n{draft_text}"
    )
    try:
        client = OpenAI(base_url=base_url, api_key=api_key)
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=8000,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "triage_dispositions",
                    "strict": True,
                    "schema": output_contract_schema(),
                },
            },
        )
        content = resp.choices[0].message.content or ""
        data = json.loads(content)
        items = data.get("dispositions") if isinstance(data, dict) else data
        return [d for d in (items or []) if isinstance(d, dict)]
    except Exception:  # noqa: BLE001  网关不支持/网络/解析异常 → 回退宽容解析
        return None


# LLM 常见的 disposition 别名 → 归一到 driver 认得的四种（accept/duplicate/reject/needs_info）。
_DISPOSITION_ALIASES = {
    "accept": "accept", "accepted": "accept", "confirm": "accept", "confirmed": "accept",
    "confirmed_bug": "accept", "confirmed_feature": "accept", "valid": "accept", "keep": "accept",
    "duplicate": "duplicate", "dup": "duplicate", "is_duplicate": "duplicate",
    "reject": "reject", "rejected": "reject", "invalid": "reject", "out_of_scope": "reject",
    "wontfix": "reject",
    "needs_info": "needs_info", "need_info": "needs_info", "needinfo": "needs_info",
    "more_info": "needs_info", "insufficient_info": "needs_info",
}


def _disposition_of(d: dict) -> str:
    """取 disposition：优先显式的动作键（`disposition` / `triage_decision` / `decision` / `action`，
    LLM 自创 schema 时常用后几者），归一到 accept/duplicate/reject/needs_info；缺失再按常见布尔/
    状态字段推断（都不匹配返回空 → 跳过）。"""
    for key in ("disposition", "triage_decision", "decision", "action"):
        raw = str(d.get(key, "")).strip().lower().replace("-", "_")
        if raw:
            return _DISPOSITION_ALIASES.get(raw, raw)
    if d.get("duplicate_of") or d.get("is_duplicate") is True:
        return "duplicate"
    if d.get("reject") is True:
        return "reject"
    if d.get("needs_info") is True:
        return "needs_info"
    status = str(d.get("status", "")).strip().lower().replace("-", "_")
    return _DISPOSITION_ALIASES.get(status, "")


def _accept_fields(kind: str, d: dict) -> dict:
    """取 accept 的 TRIAGE 字段：优先 `fields`；缺失时兼容 agent 把字段平铺在顶层（root_cause/边界/
    验收…）——按该 kind 的 schema key/label 从顶层挑。仍缺的字段留空，交给 schema_validate 判降级。"""
    raw = d.get("fields") or {}
    if not raw:
        known = {f.key for f in schema_fields_of(kind=kind)} | {
            _norm_label(f.label) for f in schema_fields_of(kind=kind)
        }
        raw = {k: v for k, v in d.items() if k in known or _norm_label(k) in known}
    return _fields_by_label_to_key(kind, raw)


class Triager:
    """triage nexau agent 驱动器：分诊 needs-triage issue → 就地分类/定位/去重/驳回。"""

    def __init__(
        self,
        tracker: IssueTracker,
        store: SessionStore,
        harness_repo: str,
        agent_def_dir: str,
        on_status: StatusFn | None = None,
        on_event: Callable[[str, str], None] | None = None,
    ) -> None:
        self._tracker = tracker
        self._store = store
        self._repo = Path(harness_repo)  # 只读 grounding：agent 读 harness 现状
        self._agent_def = Path(agent_def_dir)
        self._on_status = on_status
        self._on_event = on_event

    def triage_once(self) -> TriageOutcome:
        backlog = self._tracker.list_open_issues()
        pending = [i for i in backlog if NEEDS_TRIAGE in i.labels]
        if not pending:
            self._emit(running=False, status="无待分诊 issue")
            return TriageOutcome()
        triaged = [i for i in backlog if TRIAGED in i.labels]
        self._emit(running=True, status=f"分诊中…（{len(pending)} 条待 triage）")

        result_text = self._run_agent(pending=pending, triaged=triaged)
        # Spec-0025 根治：先经约束解码归一（json_schema 强制成合规 disposition，杜绝字段漂移/非法优先级）；
        # 归一失败（网关不支持/异常）才回退宽容解析 _parse_dispositions，绝不因归一失败丢整轮。
        dispositions = _normalize_dispositions(result_text, pending_numbers={i.number for i in pending})
        if dispositions is None:
            dispositions = _parse_dispositions(result_text)

        by_number = {i.number: i for i in pending}
        outcome = TriageOutcome()
        for d in dispositions:
            try:
                self._apply(d, by_number=by_number, outcome=outcome)
            except Exception:  # noqa: BLE001  单条落库失败（set_labels 等）不拖垮其余 disposition
                pass

        self._emit(
            running=False,
            status=(
                f"分诊 {outcome.handled} 条：采纳 {len(outcome.accepted)}、"
                f"重复 {len(outcome.duplicate)}、驳回 {len(outcome.rejected)}、"
                f"待补 {len(outcome.needs_info)}"
            ),
            detail=result_text or None,
        )
        return outcome

    def _apply(self, d: dict, *, by_number: dict, outcome: TriageOutcome) -> None:
        try:
            num = int(_issue_num(d))  # 兼容 issue / issue_number
        except (TypeError, ValueError):
            return
        issue = by_number.get(num)
        if issue is None:  # 不在本轮待分诊集合里 → 跳过（防越界改动）
            return
        disp = _disposition_of(d)  # 显式 disposition 或从布尔/status 推断

        if disp == "accept":
            kind = str(d.get("kind", "")).strip().lower()
            if kind not in USER_KINDS:  # 非法 kind → 当信息不足处理（下一轮重来）
                self._reject(issue, NEEDS_INFO, f"triage 给了非法 kind {kind!r}", outcome)
                return
            fields = _accept_fields(kind, d)  # fields 或平铺顶层的字段
            errs = schema_validate(kind=kind, fields=fields, section="triage")
            if errs:  # TRIAGE 字段没填全 → 降级 needs_info（保证采纳的 issue 定位完整）
                self._reject(issue, NEEDS_INFO, f"triage 定位不全：{'；'.join(errs)}", outcome)
                return
            priority = (
                str(d.get("priority", "")).strip().upper()
            )  # triage 按严重度×体感判，非法则不打
            self._tracker.set_labels(num, _confirmed_labels(list(issue.labels), kind, priority))
            body = schema_render(kind=kind, fields=fields, section="triage")
            self._safe_comment(num, f"## Triage 定位\n\n{body}")
            outcome.accepted.append(num)

        elif disp == "duplicate":
            of = d.get("of") or d.get("duplicate_of")  # 兼容 of / duplicate_of
            note = str(d.get("note", "")).strip()
            # 去 needs-triage（否则关闭的重复票前端仍显示"待 triage"）——重复也是一种已分诊结局。
            self._tracker.set_labels(num, [x for x in issue.labels if x != NEEDS_TRIAGE])
            self._safe_comment(num, f"duplicate of #{of}{('：' + note) if note else ''}")
            self._safe_close(num, f"duplicate of #{of}")
            outcome.duplicate.append(num)

        elif disp in ("reject", "needs_info"):
            label = REJECTED if disp == "reject" else NEEDS_INFO
            self._reject(issue, label, str(d.get("reason", "")).strip(), outcome)
        # 未知 disposition：忽略（issue 仍 needs-triage，下轮再分诊）

    def _reject(self, issue, label: str, reason: str, outcome: TriageOutcome) -> None:
        """打否决标签（rejected/needs-info）+ 写原因 + 关闭。"""
        self._tracker.set_labels(issue.number, _rejected_labels(list(issue.labels), label))
        head = "驳回" if label == REJECTED else "信息不足"
        self._safe_comment(issue.number, f"{head}：{reason or '（未给原因）'}")
        self._safe_close(issue.number, f"{head}：{reason}")
        (outcome.rejected if label == REJECTED else outcome.needs_info).append(issue.number)

    def _safe_comment(self, number: int, body: str) -> None:
        try:
            self._tracker.add_comment(number, body)
        except Exception:  # noqa: BLE001  单条挂链失败不拖垮其余
            pass

    def _safe_close(self, number: int, reason: str) -> None:
        try:
            self._tracker.set_state(number, "closed", reason)
        except Exception:  # noqa: BLE001
            pass

    def _run_agent(self, *, pending: list, triaged: list) -> str:
        os.environ["SANDBOX_WORK_DIR"] = str(self._repo)  # 只读 grounding = harness 仓
        from nexau import Agent, AgentConfig  # noqa: PLC0415  运行时依赖，懒加载

        cfg = AgentConfig.from_yaml(config_path=self._agent_def / "agent.yaml")
        if self._on_event is not None:
            from auto_designer.loop.live_tracer import StepTracer  # noqa: PLC0415

            cfg.resolved_tracer = StepTracer(self._on_event)
        agent = Agent(config=cfg)
        # 注意：triage 只做「issue 规范化」——只给它 raw issue + 只读代码 + 按需拉的单局轨迹（轨迹里含
        # 那局的体感分，供判优先级）。**不给聚合 runtime_agg / 全局体感曲线**——那是 synthesize 的 PM 视角。
        msg = (
            "逐条**规范化**下面「待 triage」的 raw 用户 issue：确认 kind、读 harness 源码 + 按 issue 号调 "
            "get_session_timeline 拉该局真实轨迹（含那局体感分）定位、判重、或驳回/needs_info。"
            "产出见系统提示的输出契约。\n"
            "**先 read_file/search_file_content 读懂相关 harness 机制再下结论**；对存疑 issue 先调 "
            "get_session_timeline(issue_number=<号>) 看那局使用事件时间线，某拍归不出因再 "
            "get_harness_beat(turn=…)、某步 truncated 且确需正文再 get_harness_step(turn=…, step_i=…)"
            "逐层下钻——别一次拉整包。\n\n"
            f"## 待 triage（{len(pending)} 条）\n{self._format_issues(pending)}\n\n"
            f"## 已 triaged（判重参照，{len(triaged)} 条）\n{self._format_issues(triaged)}\n\n"
            "最后用 complete_task 交回：result 里只放一个 JSON 数组（每条待 triage issue 一项）。"
        )
        with bind_session_store(self._store):
            out = _run_with_timeout(lambda: agent.run(message=msg), _TRIAGE_TIMEOUT)
        return _unwrap_result(out)

    @staticmethod
    def _format_issues(issues: list) -> str:
        if not issues:
            return "（无）"
        return "\n".join(
            f"- #{i.number} [{','.join(i.labels)}] {i.title}\n  {i.body}" for i in issues
        )

    def _emit(self, *, running: bool, status: str, **kw: object) -> None:
        if self._on_status is not None:
            self._on_status(running=running, status=status, **kw)

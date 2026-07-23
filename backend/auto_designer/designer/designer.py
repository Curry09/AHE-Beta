# synthesize agent：designer 收窄为纯结构综合——在已 triaged backlog 上跨 issue 找根因、产 RFC。
"""Designer = synthesize agent：综合全局的 nexau agent（对偶于 triage 的逐条梳理、开发者的局部补丁）。

Spec-0025/T4：designer 拆分后只保留 **synthesize** 这半——逐条分类/定位/去重/驳回已移交 triage agent
（designer/triage.py）。它读**已 groomed（triaged）的工作项 backlog（含跨轮积压）+ 体感曲线 + 运行时
行为聚合**，只读查看 harness 现状、按需拉 god-view 轨迹，跳出单条 issue 找跨 issue 的结构性根因，产
0..n 条 **RFC**（打 `RFC` 标签，凌驾 type；covers/supersede 它综合的局部 triaged issue，最高 dev
预算）写回 tracker，由开发者后续领取落地。designer 不碰 git、不改文件、不关 raw issue——只提方向。
产出形态与 triage/用户/开发者侧一致（agent 出草稿、driver 落库），彼此解耦。
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from auto_designer.designer.issue_schema import RFC_LABEL, SUPERSEDED, TRIAGED
from auto_designer.designer.issue_schema import fields_of as _schema_fields_of
from auto_designer.designer.issue_schema import render as _schema_render
from auto_designer.designer.issue_schema import validate as _schema_validate
from auto_designer.designer.runtime_agg import aggregate_runtime, format_runtime_agg
from auto_designer.designer.session_timeline import bind_session_store
from auto_designer.models import IssueDraft
from auto_designer.tracker.base import IssueTracker
from auto_designer.user.session_store import SessionStore

# Spec-0025/T4：designer 收窄为纯 synthesize——只在已 groomed(triaged) backlog 上找跨 issue 结构根因，
# 产 RFC（凌驾 type 的结构综合提案），covers/supersede 它综合的局部 triaged issue。逐条分诊/格式化已
# 移交 triage agent（designer/triage.py）。RFC_LABEL 取代旧的 design 标签。
DESIGN_LABEL = RFC_LABEL  # 向后兼容别名（旧测/引用）；语义现为 RFC
# 一次 propose_once 是多轮工具调用（读文件 + 综合），给足硬超时兜底防总挂死。
_DESIGN_TIMEOUT = 900
# 拆信封的最大层数：实测 nexau 会把信封再 JSON 编码一层（故 ≥2），留一层余量；有界防畸形输入打转。
_UNWRAP_MAX_DEPTH = 4


StatusFn = Callable[..., None]


def _unwrap_result(out: object) -> str:
    """拆 nexau 的 complete_task 信封 → `output.result`；非信封原样返回（Spec-0018/T1）。

    agent 用 `complete_task` 交付时，nexau 把结果套进信封、真正的 JSON 数组成了信封里的**字符串**：

        {"success": true, "status": "TASK_COMPLETED", "output": {"result": "[{...}]"}}

    而 `_parse_proposals` 的平衡括号扫描**刻意不进字符串内部**（防被散文里的 `[]` 带偏，是对的设计），
    于是扫不到顶层数组 → 静默记「本轮无提案」。实测代价：8 轮长跑 6 条结构性提案 0 条进 backlog，且
    **反向激励**——agent 听话调 complete_task 就被丢，不听话直接吐裸数组反而入库。信封在信封层拆，
    解析器保持严格。

    实测信封还会被**再编码一层**（返回值是「信封 JSON 的 JSON 字符串」，`json.loads` 一次只得到 str），
    故按层剥（有界，防畸形输入下打转）。

    非信封（裸 JSON 数组 / ```json 围栏 / 散文 / 畸形 JSON）一律回落原文，既有路径行为不变。
    harness 侧的同名同源处置见 `harness_template/entry.py::_unwrap_reply`。
    """
    text = out if isinstance(out, str) else str(out)
    node: object = text
    for _ in range(_UNWRAP_MAX_DEPTH):
        if not isinstance(node, str):
            break
        try:
            node = json.loads(node)
        except (ValueError, TypeError):
            return text  # 非 JSON（散文/围栏/半截 JSON）→ 交给 _parse_proposals 按原路解析
    if not isinstance(node, dict):
        return text  # 裸 JSON 数组等：本就是 _parse_proposals 认得的形状，原样透传
    output = node.get("output")
    result = output.get("result") if isinstance(output, dict) else None
    if isinstance(result, str):
        return result
    if isinstance(result, list | dict):
        # agent 有时把数组本体（而非其字符串形式）直接放进 result，两种都要接。
        return json.dumps(result, ensure_ascii=False)
    return text  # 是 dict 但不是 complete_task 信封 → 回落原文，不臆断


@dataclass
class DesignOutcome:
    """一次 propose_once 的结果：产出的提案 issue 号列表。"""

    proposal_numbers: list[int] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.proposal_numbers)


@dataclass(frozen=True)
class _Proposal:
    """一条解析后的 RFC 提案（Spec-0025/T4）：标题 + RFC 字段(中文 label 键) + 覆盖的 triaged 票号。"""

    title: str
    fields: dict
    covers: tuple[int, ...] = ()


def _rfc_fields_by_label(fields: dict) -> dict:
    """agent 用中文 label 填的 RFC 字段 → schema key（问题→problem 等）；未知 label 原样保留。"""
    label_to_key = {f.label: f.key for f in _schema_fields_of(kind="rfc")}
    return {label_to_key.get(str(k), str(k)): v for k, v in fields.items()}


def _parse_covers(raw: object) -> tuple[int, ...]:
    """提案的 covers 字段 → 去重正整数元组；非列表/非法元素静默丢弃（宽进严出）。"""
    if not isinstance(raw, list):
        return ()
    out: list[int] = []
    for x in raw:
        # bool 是 int 子类，需显式排除（True 会被当 #1）。
        if isinstance(x, bool) or not isinstance(x, int) or x <= 0:
            continue
        if x not in out:
            out.append(x)
    return tuple(out)


def _iter_top_level_arrays(s: str):
    """扫描出所有**顶层**平衡的 [...] 片段，尊重字符串字面量与转义（防被内嵌 [] / 散文带偏）。"""
    depth = 0
    start = -1
    in_str = False
    esc = False
    for i, ch in enumerate(s):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "[":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "]":
            if depth > 0:
                depth -= 1
                if depth == 0 and start != -1:
                    yield s[start : i + 1]
                    start = -1


def _run_with_timeout(call: Callable[[], object], timeout: int) -> object:
    """daemon 线程跑 call，超时抛 TimeoutError（丢弃线程，不阻塞进程）。"""
    box: dict = {}

    def target() -> None:
        try:
            box["out"] = call()
        except Exception as exc:  # noqa: BLE001  透传给调用方
            box["err"] = exc

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise TimeoutError(f"designer agent 超时 >{timeout}s")
    if "err" in box:
        raise box["err"]
    return box.get("out")


class Designer:
    """创新者 nexau agent 驱动器：综合全局 → 产结构性设计提案 → 落 tracker。"""

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
        self._store = store  # 体感曲线数据源（本地 SessionStore 索引）
        self._repo = Path(harness_repo)  # 只读 grounding：agent 看 harness 现状
        self._agent_def = Path(agent_def_dir)
        self._on_status = on_status
        self._on_event = (
            on_event  # 过程流回调 (kind, text)：assistant 发言/工具调用/结果，看板时间线用
        )

    def propose_once(self) -> DesignOutcome:
        backlog = self._tracker.list_open_issues()
        # Spec-0025/T4：synthesize 只在**已 groomed（triaged）**的工作项上找跨条根因（含跨轮积压）；
        # 排除 RFC 自身与已 superseded 的（不做 RFC 互指、不重复综合已被取代的）。
        triaged = [
            i
            for i in backlog
            if TRIAGED in i.labels and RFC_LABEL not in i.labels and SUPERSEDED not in i.labels
        ]
        trend = self._feeling_trend()
        # 任务无关机制层数字：扫已落盘 steps/reply + 仓内预算钮（不改协议、不碰 a 段）。
        runtime = format_runtime_agg(aggregate_runtime(store=self._store, harness_repo=self._repo))
        self._emit(running=True, status=f"综合中…（{len(triaged)} 条 triaged）")

        result_text = self._run_agent(triaged=triaged, trend=trend, runtime=runtime)
        proposals = self._parse_proposals(result_text)

        # covers 只认本轮 triaged 集合里的号（指向不存在/未 triaged/已 superseded 的号静默跳过）。
        by_number = {i.number: i for i in triaged}

        numbers: list[int] = []
        if proposals:
            self._tracker.ensure_labels([RFC_LABEL, SUPERSEDED])
        for prop in proposals:
            fields = _rfc_fields_by_label(prop.fields)
            if _schema_validate(kind="rfc", fields=fields, section="triage"):
                continue  # RFC 字段没填全 → 跳过（不产半成品结构提案）
            covers = tuple(n for n in prop.covers if n in by_number)
            body = _schema_render(kind="rfc", fields=fields)
            if covers:
                # 机器可读行 = 覆盖关系单一真源（消费方：dev 两级连带关闭、web 徽标）。
                body = f"{body}\n\ncovers: {' '.join(f'#{n}' for n in covers)}"
            ref = self._tracker.create_issue(
                IssueDraft(title=str(prop.title), body=body, labels=[RFC_LABEL])
            )
            numbers.append(ref.number)
            for n in covers:  # 被综合的局部 triaged issue → superseded（从 dev 可领集合排除）
                self._mark_superseded(issue=by_number[n], rfc_number=ref.number)

        self._emit(
            running=False,
            status=(f"提了 {len(numbers)} 条 RFC" if numbers else "本轮无结构性 RFC"),
            proposals=numbers,
            detail=(result_text or None),  # 最终报告全文（详情面板展示，不截断）
        )
        return DesignOutcome(proposal_numbers=numbers)

    def _mark_superseded(self, *, issue, rfc_number: int) -> None:
        """把被 RFC 综合的 triaged issue 标 superseded（保留原标签）+ 挂链，从 dev 可领集合排除。"""
        try:
            new_labels = list(dict.fromkeys([*issue.labels, SUPERSEDED]))
            self._tracker.set_labels(issue.number, new_labels)
            self._tracker.add_comment(issue.number, f"superseded by #{rfc_number}")
        except Exception:  # noqa: BLE001  单条挂链失败不影响其余与 RFC 本身
            pass

    def _run_agent(
        self,
        *,
        triaged: list,
        trend: list[tuple[str, int, str, str]],
        runtime: str,
    ) -> str:
        os.environ["SANDBOX_WORK_DIR"] = str(self._repo)  # 只读 grounding：sandbox = harness 仓
        from nexau import Agent, AgentConfig  # noqa: PLC0415  运行时依赖，懒加载

        cfg = AgentConfig.from_yaml(config_path=self._agent_def / "agent.yaml")
        if self._on_event is not None:
            # 过程流（assistant 发言 + 逐工具调用/结果）流到看板时间线（黑盒 run 变逐步可观测），
            # 见 loop/live_tracer。
            from auto_designer.loop.live_tracer import (
                StepTracer,  # noqa: PLC0415  依赖 nexau，懒加载
            )

            cfg.resolved_tracer = StepTracer(self._on_event)
        agent = Agent(config=cfg)
        msg = (
            "下面是**已 triaged 的工作项 backlog**（含跨轮积压）+ 体感曲线 + 运行时行为聚合。逐条的分类/"
            "定位已由 triage 做完；你的活是**跳出单条，找跨 issue 的结构性根因**，产 0..n 条 **RFC**"
            "（结构综合提案；宁缺毋滥，无跨条主题就返回 `[]`——大多数轮可能没有，别硬凑）。\n"
            "**先 read_file 读懂 harness 源码**（`agents/main.md` + `entry.py` + `agent.yaml`，看清超时/"
            "重试/迭代上限/交付方式这些一级钮）再提；没读机制源码别断言机制根因。\n"
            "**你只给「问题 + 根因 + 方向」，不写实现**：绝不写 manifest/checkpoint/gate、schema、分步"
            "协议这类施工细节（照抄就能敲键盘=越权）。\n"
            "**RFC 综合多条 triaged issue 时，用 covers 声明**：若某 RFC 的根因涵盖 backlog 里若干条 "
            'triaged issue（修好它这些就该让位），在该项加 `"covers": [票号,…]`——编排会把它们标 '
            "superseded（从 dev 领取排除）、并在 RFC 落地后连带关闭；不确定就别填。\n\n"
            f"## 已 triaged backlog（{len(triaged)} 条）\n{self._format_backlog(triaged)}\n\n"
            f"## 体感曲线（时间, 1-4 分）\n{self._format_trend(trend)}\n\n"
            f"## 运行时行为聚合（任务无关，只给数字）\n{runtime}\n\n"
            "对某条 issue 或某个体感点有疑惑时，调 `get_session_timeline`（issue_number=… 或 "
            "session_id=…）看该局落盘的 god-view 轨迹，再下结论；不要直接读 sessions/ 原始文件。\n\n"
            "最后用 complete_task 交回：result 里只放一个 JSON 数组，每项一个 RFC——含 `title`、"
            '`fields`（RFC 字段：问题/根因/涉及issue/方向/验收，中文 label 键）、可选 `covers`；无 RFC 则 `[]`。'
        )
        with bind_session_store(self._store):
            out = _run_with_timeout(lambda: agent.run(message=msg), _DESIGN_TIMEOUT)
        return _unwrap_result(out)

    def _feeling_trend(self) -> list[tuple[str, int, str, str]]:
        """体感随时间：[(created_at, score, reason, session_id)]，按时间升序。

        reason = 用户末态那句「为什么」。session_id 供 get_session_timeline 按体感点取用。
        """
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
    def _format_backlog(backlog: list) -> str:
        if not backlog:
            return "（当前无 open issue）"
        return "\n".join(
            f"- #{i.number} [{','.join(i.labels)}] {i.title}\n  {i.body}" for i in backlog
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
        """从 agent 的 result 文本里抽出 JSON 数组并解析成 _Proposal 列表。

        容忍 ```json 代码块与前后散文。裸输出时**不再**用 find('[')→rfind(']') 一把抓
        （那会被散文/字符串里的 [] 或多段数组带偏、抠出非法片段 → 静默吞掉提案，与 persona
        _parse_json 曾踩的同类坑），改用尊重字符串转义的**平衡括号扫描**取最后一个能解析的顶层
        数组。解析失败或非列表一律返回空列表（本轮无提案），不抛错——designer 出错不该拖垮闭环。
        Spec-0020/T1：每项可带可选 covers: list[int]（该提案覆盖的 bug 票号），非法值静默丢弃。
        """
        if not text:
            return []
        fenced = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
        data: object | None = None
        if fenced is not None:
            try:
                data = json.loads(fenced.group(1))
            except (ValueError, TypeError):
                data = None
        if data is None:
            for chunk in _iter_top_level_arrays(text):  # 保留最后一个成功者
                try:
                    parsed = json.loads(chunk)
                except (ValueError, TypeError):
                    continue
                if isinstance(parsed, list):
                    data = parsed
        if not isinstance(data, list):
            return []
        proposals: list[_Proposal] = []
        for item in data:
            if not isinstance(item, dict) or not item.get("title"):
                continue
            fields = item.get("fields")
            proposals.append(
                _Proposal(
                    title=str(item["title"]),
                    fields=fields if isinstance(fields, dict) else {},
                    covers=_parse_covers(item.get("covers")),
                )
            )
        return proposals

    def _emit(self, *, running: bool, status: str, **kw: object) -> None:
        if self._on_status is not None:
            self._on_status(running=running, status=status, **kw)

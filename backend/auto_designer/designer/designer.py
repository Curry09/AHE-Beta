# 创新者侧：designer = 带只读工具的 nexau agent，综合全局 backlog + 体感曲线产结构性设计提案。
"""Designer：创新者 = 综合全局的 nexau agent（对偶于开发者的「局部补丁」）。

开发者 agent 只做聚焦的局部修改，难产生结构性改进（会把轨迹特征带进 harness）。designer 补上这一环：
读**全量 open issue backlog + 体感曲线 + 运行时行为聚合**，只读查看 harness 现状，跳出单条 issue
找跨 issue 的结构性根因，产出 0..n 条**设计提案**（打 `design` 标签）写回 tracker，由开发者后续领取
落地。designer 不碰 git、不改文件——它只提方向，不动手。产出形态与用户 agent 一致（agent 出草稿、
driver 落库），与开发者侧解耦。
"""

from __future__ import annotations

import json
import os
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from auto_designer.designer.runtime_agg import aggregate_runtime, format_runtime_agg
from auto_designer.models import IssueDraft
from auto_designer.tracker.base import IssueTracker
from auto_designer.user.session_store import SessionStore

# designer 的默认标签：结构性提案与用户 agent 产的 bug/feature 区分，便于观测（开发者领取不分流）。
DESIGN_LABEL = "design"
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
    """一条解析后的提案：issue 草稿 + 它声明覆盖的 bug 票号（Spec-0020/T1）。"""

    draft: IssueDraft
    covers: tuple[int, ...] = ()


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
        trend = self._feeling_trend()
        # 任务无关机制层数字：扫已落盘 steps/reply + 仓内预算钮（不改协议、不碰 a 段）。
        runtime = format_runtime_agg(aggregate_runtime(store=self._store, harness_repo=self._repo))
        self._emit(running=True, status=f"综合全局中…（{len(backlog)} open issue）")

        result_text = self._run_agent(backlog=backlog, trend=trend, runtime=runtime)
        proposals = self._parse_proposals(result_text)

        # Spec-0020/T1：covers 只认「开局 backlog 里 open 且非 design」的票——指向不存在/已 closed/
        # design 票的号静默跳过（覆盖语义是"设计票整合 bug"，不做设计票互指）。
        coverable = {i.number for i in backlog if DESIGN_LABEL not in i.labels}

        numbers: list[int] = []
        if proposals:
            self._tracker.ensure_labels([DESIGN_LABEL])
        for prop in proposals:
            draft = prop.draft
            # 强制打上 design 标签（去重），保证提案在 tracker 里可辨识。
            labels = list(dict.fromkeys([*draft.labels, DESIGN_LABEL]))
            covers = tuple(n for n in prop.covers if n in coverable)
            body = draft.body
            if covers:
                # 机器可读行 = 覆盖关系单一真源（消费方：dev 领取降权/连带关闭、web 徽标）。
                body = f"{body}\n\ncovers: {' '.join(f'#{n}' for n in covers)}"
            ref = self._tracker.create_issue(IssueDraft(title=draft.title, body=body, labels=labels))
            numbers.append(ref.number)
            for n in covers:
                try:
                    self._tracker.add_comment(n, f"covered-by: #{ref.number}")
                except Exception:  # noqa: BLE001  挂链是可读性旁路，单条失败不影响其余与提案本身
                    pass

        self._emit(
            running=False,
            status=(f"提了 {len(numbers)} 条设计提案" if numbers else "本轮无结构性提案"),
            proposals=numbers,
            detail=(result_text or None),  # 最终报告全文（详情面板展示，不截断）
        )
        return DesignOutcome(proposal_numbers=numbers)

    def _run_agent(
        self,
        *,
        backlog: list,
        trend: list[tuple[str, int, str]],
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
            "综合下面的全量 open issue backlog、体感曲线与运行时行为聚合，找跨 issue 的结构性根因，"
            "产出 0..n 条结构性设计提案（宁缺毋滥；无值得提的方向就返回 `[]`）。\n"
            "**先 read_file 读懂 harness 源码**（`agents/main.md` + `entry.py` + `agent.yaml`，"
            "看清超时/重试/迭代上限/交付方式这些一级钮）再提；没读机制源码别断言机制根因。\n"
            "**你只给「问题 + 方向」，不写实现**：绝不在 body 里写 manifest/checkpoint/gate、"
            "schema、分步协议这类施工细节（照抄就能敲键盘=越权，退回只留问题和方向）。\n"
            "**动笔前先按系统提示里的「重复判定 rubric」逐条过滤**：每条候选对照下面 backlog 每条 issue "
            "及你本轮其它候选，命中 R1 同根因 / R2 同施力点方向 / R3 开发者视角 subsume 任一即为重复，不提；"
            "只提带来新根因或新施力点的方向。若 backlog 里多条依 rubric 互为重复或已被现状覆盖，"
            "用一条整合性提案点明「#X/#Y 系同一根因，建议合并/关闭」，而非换皮再加一条。\n"
            "**整合性提案请用 covers 字段声明覆盖关系**：若某条提案已包含 backlog 里若干 bug 的"
            "根因（修好它这些 bug 即解决），在该项加 `\"covers\": [票号,…]`（只填 bug 票号）——"
            "编排会据此让被覆盖 bug 让位于你的提案、并在提案落地后连带关闭它们；"
            "不确定是否真覆盖就别填（错误覆盖会延迟真实 bug 的处理）。\n\n"
            f"## open issue backlog（{len(backlog)} 条）\n{self._format_backlog(backlog)}\n\n"
            f"## 体感曲线（时间, 1-4 分）\n{self._format_trend(trend)}\n\n"
            f"## 运行时行为聚合（任务无关，只给数字）\n{runtime}\n\n"
            "最后用 complete_task 交回：result 里只放一个 JSON 数组"
            "（每项含 title/body/labels，可选 covers），无提案则 `[]`。"
        )
        out = _run_with_timeout(lambda: agent.run(message=msg), _DESIGN_TIMEOUT)
        return _unwrap_result(out)

    def _feeling_trend(self) -> list[tuple[str, int, str]]:
        """体感随时间：[(created_at, score, reason)]，按时间升序。空数据源返回空序列。

        reason = 用户末态那句「为什么」（feeling.reason）。设计师光看分数无法判根因——
        「延迟/等待本身就是痛点」这类只能从 reason 里读出（老索引无此键时回落空串）。
        """
        rows = sorted(self._store.index(), key=lambda e: e["created_at"])
        return [(e["created_at"], e["score"], str(e.get("reason", ""))) for e in rows]

    @staticmethod
    def _format_backlog(backlog: list) -> str:
        if not backlog:
            return "（当前无 open issue）"
        return "\n".join(
            f"- #{i.number} [{','.join(i.labels)}] {i.title}\n  {i.body}" for i in backlog
        )

    @staticmethod
    def _format_trend(trend: list[tuple[str, int, str]]) -> str:
        if not trend:
            return "（暂无体感数据）"
        lines = []
        for ts, score, reason in trend:
            why = f" — {reason}" if reason else ""
            lines.append(f"- {ts}: {score}{why}")
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
            proposals.append(
                _Proposal(
                    draft=IssueDraft(
                        title=str(item["title"]),
                        body=str(item.get("body", "")),
                        labels=[str(x) for x in item.get("labels", []) if x],
                    ),
                    covers=_parse_covers(item.get("covers")),
                )
            )
        return proposals

    def _emit(self, *, running: bool, status: str, **kw: object) -> None:
        if self._on_status is not None:
            self._on_status(running=running, status=status, **kw)

# 创新者侧：designer = 带只读工具的 nexau agent，综合全局 backlog + 体感曲线产结构性设计提案。
"""Designer：创新者 = 综合全局的 nexau agent（对偶于开发者的「局部补丁」）。

开发者 agent 只做聚焦的局部修改，难产生结构性改进（会把轨迹特征带进 harness）。designer 补上这一环：
读**全量 open issue backlog + 体感曲线**，只读查看 harness 现状（agents/main.md），跳出单条 issue
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

from auto_designer.models import IssueDraft
from auto_designer.tracker.base import IssueTracker
from auto_designer.user.session_store import SessionStore

# designer 的默认标签：结构性提案与用户 agent 产的 bug/feature 区分，便于观测（开发者领取不分流）。
DESIGN_LABEL = "design"
# 一次 propose_once 是多轮工具调用（读文件 + 综合），给足硬超时兜底防总挂死。
_DESIGN_TIMEOUT = 900

StatusFn = Callable[..., None]


@dataclass
class DesignOutcome:
    """一次 propose_once 的结果：产出的提案 issue 号列表。"""

    proposal_numbers: list[int] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.proposal_numbers)


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
        on_step: Callable[[str], None] | None = None,
    ) -> None:
        self._tracker = tracker
        self._store = store  # 体感曲线数据源（本地 SessionStore 索引）
        self._repo = Path(harness_repo)  # 只读 grounding：agent 看 harness 现状
        self._agent_def = Path(agent_def_dir)
        self._on_status = on_status
        self._on_step = on_step  # 逐步过程回调（每个工具调用一条），看板时间线用

    def propose_once(self) -> DesignOutcome:
        backlog = self._tracker.list_open_issues()
        trend = self._feeling_trend()
        self._emit(running=True, status=f"综合全局中…（{len(backlog)} open issue）")

        result_text = self._run_agent(backlog=backlog, trend=trend)
        drafts = self._parse_proposals(result_text)

        numbers: list[int] = []
        if drafts:
            self._tracker.ensure_labels([DESIGN_LABEL])
        for draft in drafts:
            # 强制打上 design 标签（去重），保证提案在 tracker 里可辨识。
            labels = list(dict.fromkeys([*draft.labels, DESIGN_LABEL]))
            ref = self._tracker.create_issue(
                IssueDraft(title=draft.title, body=draft.body, labels=labels)
            )
            numbers.append(ref.number)

        self._emit(
            running=False,
            status=(f"提了 {len(numbers)} 条设计提案" if numbers else "本轮无结构性提案"),
            detail=(result_text[:800] if result_text else None),
        )
        return DesignOutcome(proposal_numbers=numbers)

    def _run_agent(self, *, backlog: list, trend: list[tuple[str, int]]) -> str:
        os.environ["SANDBOX_WORK_DIR"] = str(self._repo)  # 只读 grounding：sandbox = harness 仓
        from nexau import Agent, AgentConfig  # noqa: PLC0415  运行时依赖，懒加载

        cfg = AgentConfig.from_yaml(config_path=self._agent_def / "agent.yaml")
        if self._on_step is not None:
            # 逐工具调用流到看板时间线（黑盒 run 变逐步可观测），见 loop/live_tracer。
            from auto_designer.loop.live_tracer import (
                StepTracer,  # noqa: PLC0415  依赖 nexau，懒加载
            )

            cfg.resolved_tracer = StepTracer(self._on_step)
        agent = Agent(config=cfg)
        msg = (
            "综合下面的全量 open issue backlog 与体感曲线，找跨 issue 的结构性根因，"
            "产出 0..n 条结构性设计提案（宁缺毋滥；无值得提的方向就返回 `[]`）。\n"
            "可先用 read_file 读 `agents/main.md` 看 harness 现状再提。\n\n"
            f"## open issue backlog（{len(backlog)} 条）\n{self._format_backlog(backlog)}\n\n"
            f"## 体感曲线（时间, 1-4 分）\n{self._format_trend(trend)}\n\n"
            "最后用 complete_task 交回：result 里只放一个 JSON 数组"
            "（每项含 title/body/labels），无提案则 `[]`。"
        )
        out = _run_with_timeout(lambda: agent.run(message=msg), _DESIGN_TIMEOUT)
        return out if isinstance(out, str) else str(out)

    def _feeling_trend(self) -> list[tuple[str, int]]:
        """体感随时间：[(created_at, score)]，按时间升序。空数据源返回空序列。"""
        rows = sorted(self._store.index(), key=lambda e: e["created_at"])
        return [(e["created_at"], e["score"]) for e in rows]

    @staticmethod
    def _format_backlog(backlog: list) -> str:
        if not backlog:
            return "（当前无 open issue）"
        return "\n".join(
            f"- #{i.number} [{','.join(i.labels)}] {i.title}\n  {i.body}" for i in backlog
        )

    @staticmethod
    def _format_trend(trend: list[tuple[str, int]]) -> str:
        if not trend:
            return "（暂无体感数据）"
        return "\n".join(f"- {ts}: {score}" for ts, score in trend)

    @staticmethod
    def _parse_proposals(text: str) -> list[IssueDraft]:
        """从 agent 的 result 文本里抽出 JSON 数组并解析成 IssueDraft 列表。

        容忍 ```json 代码块与前后散文：取第一个 `[` 到最后一个 `]` 的切片解析。解析失败或非列表
        一律返回空列表（本轮无提案），不抛错——designer 出错不该拖垮闭环。
        """
        if not text:
            return []
        fenced = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
        blob = fenced.group(1) if fenced else None
        if blob is None:
            start, end = text.find("["), text.rfind("]")
            if start == -1 or end <= start:
                return []
            blob = text[start : end + 1]
        try:
            data = json.loads(blob)
        except (ValueError, TypeError):
            return []
        if not isinstance(data, list):
            return []
        drafts: list[IssueDraft] = []
        for item in data:
            if not isinstance(item, dict) or not item.get("title"):
                continue
            drafts.append(
                IssueDraft(
                    title=str(item["title"]),
                    body=str(item.get("body", "")),
                    labels=[str(x) for x in item.get("labels", []) if x],
                )
            )
        return drafts

    def _emit(self, *, running: bool, status: str, **kw: object) -> None:
        if self._on_status is not None:
            self._on_status(running=running, status=status, **kw)

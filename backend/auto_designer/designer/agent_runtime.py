# Spec-0029/T2：agent 公共运行时——「跑一个 nexau agent + 读它的 submit 产物」的单一实现。
"""四个 driver（triage / synthesize / divergent / owner）此前各抄一份的公共逻辑收拢于此：

- `run_with_timeout`：daemon 线程跑 call + 超时兜底；用 `contextvars.copy_context()` 把主线程
  context（含 bind_session_store 注入的 SessionStore）带进 worker 线程——新起线程默认空 context，
  否则 agent 在 worker 线程里调 get_session_timeline 会报「session store not bound」（线上实测过）。
- `run_agent_def`：加载 agent 定义并跑一轮——设 SANDBOX_WORK_DIR（绝对路径，防 cwd 漂移）、
  AgentConfig.from_yaml、StepTracer（看板过程流）、bind_session_store、超时；返回 agent.run 的
  返回值（submit stop-tool 的回显 JSON；非 str 时 dumps 兜底）。
- `read_submit`：从 agent.run 返回值取 submit 载荷数组——有界逐层 json.loads（兼容 nexau 可能
  再编码一层）直到 dict、取 key；未调 submit / 解析失败返回 None（调用方 no-op 兜底）。
- `norm_label`：label 归一（去空白比较），容忍 LLM 的空格差异。

driver 由此瘦成「拼 prompt → run_agent_def → read_submit → 写 tracker」。
"""

from __future__ import annotations

import contextvars
import json
import os
import threading
from collections.abc import Callable
from pathlib import Path

from auto_designer.designer.session_timeline import bind_session_store
from auto_designer.usage import bind_usage_context
from auto_designer.user.session_store import SessionStore

# 拆返回值再编码的最大层数：实测 nexau 会把返回再 JSON 编码一层（故 ≥2），留余量；有界防畸形输入打转。
_UNWRAP_MAX_DEPTH = 4


def run_with_timeout(call: Callable[[], object], timeout: int) -> object:
    """daemon 线程跑 call，超时抛 TimeoutError（丢弃线程，不阻塞进程）；contextvars 跨线程传递。"""
    ctx = contextvars.copy_context()
    box: dict = {}

    def target() -> None:
        try:
            box["out"] = ctx.run(call)
        except Exception as exc:  # noqa: BLE001  透传给调用方
            box["err"] = exc

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise TimeoutError(f"agent 超时 >{timeout}s")
    if "err" in box:
        raise box["err"]
    return box.get("out")


def run_agent_def(
    agent_def_dir: str | Path,
    message: str,
    *,
    store: SessionStore,
    repo: str | Path,
    role: str,
    timeout: int,
    on_event: Callable[[str, str], None] | None = None,
    max_iterations: int | None = None,
) -> str:
    """加载 agent_def_dir 的 nexau agent 定义、以 message 跑一轮，返回 agent.run 的返回值（str）。

    repo = 只读 grounding 的 harness 仓（设进 SANDBOX_WORK_DIR，绝对路径防 cwd 漂移）；store 经
    bind_session_store 注入供 get_session_timeline/beat/step 工具读取；role 由调用角色显式提供，
    不从目录名推断；on_event 给看板过程流；max_iterations 可收紧预算（如 Owner 评审段短预算），
    None 用定义里的值。
    """
    os.environ["SANDBOX_WORK_DIR"] = str(Path(repo).resolve())
    from nexau import Agent, AgentConfig  # noqa: PLC0415  运行时依赖，懒加载

    cfg = AgentConfig.from_yaml(config_path=Path(agent_def_dir) / "agent.yaml")
    if max_iterations is not None:
        cfg.max_iterations = min(int(cfg.max_iterations or max_iterations), max_iterations)
    from auto_designer.loop.live_tracer import StepTracer  # noqa: PLC0415  依赖 nexau，懒加载

    cfg.resolved_tracer = StepTracer(on_event or (lambda _kind, _text: None))
    agent = Agent(config=cfg)
    with bind_session_store(store), bind_usage_context(role=role, operation="nexau-agent"):
        out = run_with_timeout(lambda: agent.run(message=message), timeout)
    # submit 工具是 stop tool：binding 回显的 JSON 即 agent.run 的返回；非 str（nexau 有时再序列化
    # 前就是对象）时 dumps 成 str，交由 read_submit 的有界 json.loads 处理。
    return out if isinstance(out, str) else json.dumps(out, ensure_ascii=False)


def read_submit(text: str, key: str) -> list[dict] | None:
    """agent.run 返回值 → submit 载荷数组（每项 dict）。

    正常路径：text 是 submit binding 回显的 `{"<key>": [...]}` JSON 串（nexau 已按 input_schema
    强校验过结构）。兼容再编码一层（有界逐层 json.loads 直到得到 dict）。agent 从未调 submit
    （撞 max_iterations 等）→ 返回的是别的文本/非合规 JSON → 返回 None，调用方本轮 no-op 兜底。
    提交了但空数组 → 返回 []（合法的「本轮无产出」）。
    """
    node: object = text
    for _ in range(_UNWRAP_MAX_DEPTH):
        if not isinstance(node, str):
            break
        try:
            node = json.loads(node)
        except (ValueError, TypeError):
            return None
    if not isinstance(node, dict):
        return None
    raw = node.get(key)
    if not isinstance(raw, list):
        return None
    return [d for d in raw if isinstance(d, dict)]


def norm_label(s: object) -> str:
    """label 归一：去掉所有空白后比较——容忍 LLM 把「涉及 issue」写成「涉及issue」这类空格差异。"""
    return "".join(str(s).split())

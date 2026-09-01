"""单一 nexau 适配层（spec-0003/T2）：把一份角色定义(prompt+工具)加载成可调用 Agent。

三角色（user/developer/test）共用：load(agent_def_dir) 读定义、构造 Agent；Agent.run(input) 执行一次
nexau 调用返回输出文本，薄封装、无状态记忆（多轮编排归消费方）。MVP 只接 nexau；CC/codex 后续在 load 内分发。
"""

from __future__ import annotations

import os
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path

# 角色定义目录下系统提示文件名（必需）。
_PROMPT_FILE = "prompt.md"
# 网关偶发 502，整次 agent.run 兜底重试次数。
_RUN_RETRIES = 4
# 单次 agent.run 硬超时（秒）：nexau 的 llm_config.timeout 实测不生效，故在此层用线程兜底防死等。
_CALL_TIMEOUT = 240


def _run_with_timeout(call: Callable[[], object], timeout: int) -> object:
    """在 daemon 线程里跑 call，超 timeout 秒未返回则抛 TimeoutError（丢弃该线程，不阻塞进程）。"""
    box: dict = {}

    def target() -> None:
        try:
            box["out"] = call()
        except Exception as exc:  # noqa: BLE001  透传给调用方判定/重试
            box["err"] = exc

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise TimeoutError(f"nexau 调用超时 >{timeout}s")
    if "err" in box:
        raise box["err"]
    return box.get("out")


# nexau 后端：(system_prompt, input) -> output_text。注入便于测试替身。
Backend = Callable[[str, str], str]


def _default_nexau_backend(system_prompt: str, user_input: str) -> str:
    """真实 nexau 后端：用 system_prompt + 环境里的 LLM_* 构造一个无工具 nexau Agent 跑一次。

    每次调用建一个全新的瞬态 Agent（无状态：上下文由调用方在 user_input 里拼好），避免历史串味。
    懒加载 nexau；未装在此显式失败。整次 run 包一层重试，扛网关 502 抽风。
    """
    from nexau import Agent  # noqa: PLC0415  运行时依赖，懒加载

    model = os.environ["LLM_MODEL"]
    base_url = os.environ["LLM_BASE_URL"]
    api_key = os.environ["LLM_API_KEY"]

    last_err: Exception | None = None
    for attempt in range(_RUN_RETRIES):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "prompt.md").write_text(system_prompt, encoding="utf-8")
            (Path(tmp) / "agent.yaml").write_text(
                "type: agent\n"
                "name: role\n"
                "max_context_tokens: 256000\n"
                "system_prompt: ./prompt.md\n"
                "system_prompt_type: string\n"
                "llm_config:\n"
                f"  model: {model}\n"
                f"  base_url: {base_url}\n"
                f"  api_key: {api_key}\n"
                # Nex-N2-Pro 是推理模型：reasoning_content 先吃 token，4096 易被推理吃光致 content=null。
                "  max_tokens: 32768\n"
                # per-call 超时：不设则 openai 客户端无限挂起；超时即触发本模块重试。
                "  timeout: 300\n"
                "  api_type: openai_chat_completion\n",
                encoding="utf-8",
            )
            try:
                agent = Agent.from_yaml(Path(tmp) / "agent.yaml")
                out = _run_with_timeout(lambda a=agent: a.run(message=user_input), _CALL_TIMEOUT)
                return out if isinstance(out, str) else out[0]
            except Exception as exc:  # 网关 502/超时 → 退避后重试
                last_err = exc
                time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"nexau 调用重试 {_RUN_RETRIES} 次仍失败：{last_err}") from last_err


class Agent:
    """加载后的可调用角色：run 是对 nexau 的薄封装，无提示工程/重试/会话记忆。"""

    def __init__(self, prompt: str, backend: Backend) -> None:
        self._prompt = prompt
        self._backend = backend

    @property
    def prompt(self) -> str:
        return self._prompt

    def run(self, user_input: str) -> str:
        return self._backend(self._prompt, user_input)  # nexau 调用失败原样透传


def load(agent_def_dir: str) -> Agent:
    """读取角色定义目录、解析 prompt，构造 Agent。目录缺失或缺 prompt.md 抛错。"""
    root = Path(agent_def_dir)
    if not root.is_dir():
        raise FileNotFoundError(f"角色定义目录不存在：{root}")
    prompt_path = root / _PROMPT_FILE
    if not prompt_path.is_file():
        raise FileNotFoundError(f"角色定义缺 {_PROMPT_FILE}：{prompt_path}")
    prompt = prompt_path.read_text(encoding="utf-8")
    return Agent(prompt=prompt, backend=_default_nexau_backend)

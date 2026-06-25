"""单一 nexau 适配层（spec-0003/T2）：把一份角色定义(prompt+工具)加载成可调用 Agent。

三角色（user/developer/test）共用：load(agent_def_dir) 读定义、构造 Agent；Agent.run(input) 执行一次
nexau 调用返回输出文本，薄封装、无状态记忆（多轮编排归消费方）。MVP 只接 nexau；CC/codex 后续在 load 内分发。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

# 角色定义目录下系统提示文件名（必需）。
_PROMPT_FILE = "prompt.md"

# nexau 后端：(system_prompt, input) -> output_text。注入便于测试替身。
Backend = Callable[[str, str], str]


def _default_nexau_backend(system_prompt: str, user_input: str) -> str:
    """真实 nexau 后端：以角色定义为系统侧上下文，对 input 执行一次调用。

    懒加载 nexau（仅运行时需要）；未安装则在此显式失败，而非 import 期拖垮整个包。
    """
    import nexau  # noqa: PLC0415  运行时依赖，懒加载

    client = nexau.Client()
    return client.run(system=system_prompt, input=user_input)


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

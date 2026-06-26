"""harness v0 入口（spec-0003/T1 种子）：单个 nexau 的逐轮 stdio JSONL 服务。

被进化对象。launcher 把它当黑盒可启动程序：从 stdin 逐行读 {"message": str}，
向 stdout 逐行写 {"reply": str}（JSONL，一读一写严格配对）。内部如何编排（这里是单 nexau，
将来可演化为多 nexau）对 launcher 不可见——开发者 agent 后续就是在改本仓内容。

真实运行：用本目录 agents/main.md 作系统提示 + 环境里的 LLM_* 构造一个 nexau Agent，
单实例维护多轮 history。需要 nexau 可 import 且 LLM_MODEL/LLM_BASE_URL/LLM_API_KEY 已注入。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_RUN_RETRIES = 4


def _build_agent():
    """以 agents/main.md 为系统提示，按环境 LLM_* 构造单个 nexau Agent。"""
    from nexau import Agent

    cfg_dir = Path(tempfile.mkdtemp(prefix="harness_agent_"))
    (cfg_dir / "prompt.md").write_text(
        (_HERE / "agents" / "main.md").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (cfg_dir / "agent.yaml").write_text(
        "type: agent\n"
        "name: harness\n"
        "system_prompt: ./prompt.md\n"
        "system_prompt_type: string\n"
        "llm_config:\n"
        f"  model: {os.environ['LLM_MODEL']}\n"
        f"  base_url: {os.environ['LLM_BASE_URL']}\n"
        f"  api_key: {os.environ['LLM_API_KEY']}\n"
        # Nex-N2-Pro 是推理模型：reasoning_content 先吃 token，4096 会被推理吃光致 content=null。
        "  max_tokens: 32768\n"
        # per-call 超时：不设则 openai 客户端无限挂起（网关偶发卡死整轮）；超时即触发 _reply 重试。
        "  timeout: 300\n"
        "  api_type: openai_chat_completion\n",
        encoding="utf-8",
    )
    return Agent.from_yaml(cfg_dir / "agent.yaml")


def _reply(agent, message: str) -> str:
    last = None
    for attempt in range(_RUN_RETRIES):
        try:
            out = agent.run(message=message)
            text = out if isinstance(out, str) else out[0]
            if text and text.strip():  # 非空才算成功
                return text
            last = "empty reply"  # 空回复（网关 200+空内容不抛异常）视为失败，不得静默返回
        except Exception as exc:  # 网关 502 抽风 → 退避重试
            last = exc
        if attempt < _RUN_RETRIES - 1:  # 末次不再睡
            time.sleep(1.5 * (attempt + 1))
    return f"[harness error] {last}"


def main() -> None:
    agent = _build_agent()  # 单实例，history 由 nexau 自身跨轮维护
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        message = json.loads(line)["message"]
        reply = _reply(agent, message)
        sys.stdout.write(json.dumps({"reply": reply}, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()

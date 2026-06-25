"""harness v0 入口（spec-0003/T1 种子）：单个 nexau 的逐轮 stdio JSONL 服务。

被进化对象。launcher 把它当黑盒可启动程序：从 stdin 逐行读 {"message": str}，
向 stdout 逐行写 {"reply": str}（JSONL，一读一写严格配对）。内部如何编排（这里是单 nexau，
将来可演化为多 nexau）对 launcher 不可见——开发者 agent 后续就是在改本仓内容。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def _build_agent():
    """加载本目录 agents/main.md 作为系统提示，构造单个 nexau agent。"""
    import nexau  # 运行时依赖：harness 自带，不复用本仓 nexau_runtime（保持独立）

    system = (Path(__file__).parent / "agents" / "main.md").read_text(encoding="utf-8")
    return nexau.Client(), system


def main() -> None:
    client, system = _build_agent()
    history: list[dict[str, str]] = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        message = json.loads(line)["message"]
        history.append({"role": "user", "content": message})
        reply = client.run(system=system, messages=history)
        history.append({"role": "assistant", "content": reply})
        sys.stdout.write(json.dumps({"reply": reply}, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()

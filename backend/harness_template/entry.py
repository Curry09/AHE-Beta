"""harness v0 入口（spec-0003/T1 种子）：单个 nexau 的逐轮 stdio JSONL 服务。

被进化对象。launcher 把它当黑盒可启动程序：从 stdin 逐行读 {"message": str}，
向 stdout 逐行写 {"reply": str}（JSONL，一读一写严格配对）。内部如何编排（这里是单 nexau，
将来可演化为多 nexau）对 launcher 不可见——开发者 agent 后续就是在改本仓内容。

真实运行：按本目录 agent.yaml（最简「只有 bash」的工具型 agent，系统提示 = agents/main.md，
LLM_* 走 ${env}）构造单个 nexau Agent，单实例维护多轮 history。bash 在一个每会话工作区
（SANDBOX_WORK_DIR）里执行，作为「用户项目」根目录。需要 nexau 可 import 且
LLM_MODEL/LLM_BASE_URL/LLM_API_KEY 已注入。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_RUN_RETRIES = 4
# 单次 agent.run 硬超时（秒）：nexau 自身的 llm_config.timeout 实测不生效，故在此层用线程兜底，
# 卡住即放弃该次（daemon 线程丢弃，不阻塞进程），保证 harness 永远在 bounded 时间内回一行。
_CALL_TIMEOUT = 240


def _run_with_timeout(agent, message, timeout):
    box: dict = {}

    def target():
        try:
            box["out"] = agent.run(message=message)
        except Exception as exc:  # noqa: BLE001  透传给调用方判定/重试
            box["err"] = exc

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        raise TimeoutError(f"agent.run 超时 >{timeout}s")
    if "err" in box:
        raise box["err"]
    return box.get("out")


def _setup_workspace() -> str:
    """每会话建一个干净工作区作 bash 的「项目根目录」，写入 SANDBOX_WORK_DIR（nexau local sandbox 读它）。"""
    ws = os.environ.get("SANDBOX_WORK_DIR")
    if not ws:
        ws = tempfile.mkdtemp(prefix="harness_ws_")
        os.environ["SANDBOX_WORK_DIR"] = ws
    return ws


def _build_agent():
    """按本目录 agent.yaml 构造工具型 nexau Agent（只挂 bash + complete_task）。"""
    from nexau import Agent, AgentConfig

    cfg = AgentConfig.from_yaml(config_path=_HERE / "agent.yaml")
    return Agent(config=cfg)


def _reply(agent, message: str, rebuild):
    """返回 (live_agent, reply)：超时重试前重建 agent，避开被放弃线程仍持的 nexau 锁。

    `_run_with_timeout` 超时时只能 raise，那个 daemon 线程杀不掉、仍持有该 (session, agent)
    的 nexau 锁并持续心跳续期 → 同 agent 重试必撞 "already locked by holder=<pid>"（自锁）。
    故超时分支换用 `rebuild()` 起一个新 agent（新 session/新锁键）再试；代价是丢该实例多轮
    history（但卡死那次本就没拿到回复，可接受）。502/空回复时线程已结束、锁已释放，保持同 agent。
    """
    last = None
    for attempt in range(_RUN_RETRIES):
        try:
            out = _run_with_timeout(agent, message, _CALL_TIMEOUT)  # 硬超时，绝不死等
            text = out if isinstance(out, str) else (out[0] if out else "")  # 工具型返回 result 串
            if text and text.strip():  # 非空才算成功
                return agent, text
            last = "empty reply"  # 空回复（网关 200+空内容不抛异常）视为失败，不得静默返回
        except TimeoutError as exc:  # 线程被放弃仍持锁 → 重建避自锁
            last = exc
            agent = rebuild()
        except Exception as exc:  # 网关 502 等 → 同 agent 退避重试（线程已结束、锁已释放）
            last = exc
        if attempt < _RUN_RETRIES - 1:  # 末次不再睡
            time.sleep(1.5 * (attempt + 1))
    return agent, f"[harness error] {last}"


def main() -> None:
    _setup_workspace()  # 先就位 SANDBOX_WORK_DIR，供 agent 的 local sandbox 读取
    agent = _build_agent()  # 单实例，history 由 nexau 自身跨轮维护
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        message = json.loads(line)["message"]
        agent, reply = _reply(agent, message, _build_agent)  # 重建后续用 live agent
        sys.stdout.write(json.dumps({"reply": reply}, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()

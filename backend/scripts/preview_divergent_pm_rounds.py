#!/usr/bin/env python3
"""用已落盘的 5 轮 SWE 闭环结果，分别跑 divergent PM（不重跑闭环、不写 Gitea）。

每轮输入对齐 synthesize：截至该轮末的体感曲线 + runtime 聚合 +（尽力）当时相关 backlog 摘要。
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # backend/
REPO = ROOT.parent
sys.path.insert(0, str(ROOT))

for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

from auto_designer.designer.runtime_agg import aggregate_runtime, format_runtime_agg
from auto_designer.designer.session_timeline import bind_session_store
from auto_designer.user.session_store import SessionStore

HARNESS = ROOT / "data" / "harness_sandbox" / "harness_repo"
AGENT_DEF = ROOT / "agent_defs" / "divergent_pm"
OUT = ROOT / "data" / "divergent_pm_preview_by_round.json"
STORE = SessionStore(ROOT / "data" / "sessions")

# 与上次闭环日志一致：最后 50 局按时间分成 5 轮 × 10
ALL = sorted(STORE.index(), key=lambda e: e["created_at"])[-50:]
ROUNDS = [ALL[i : i + 10] for i in range(0, 50, 10)]


def _format_trend(entries: list[dict]) -> str:
    if not entries:
        return "（暂无体感数据）"
    lines = []
    for e in entries:
        why = f" — {e.get('reason', '')}" if e.get("reason") else ""
        sid = e.get("session_id", "")
        sid_bit = f" [session={sid}]" if sid else ""
        lines.append(f"- {e['created_at']}{sid_bit}: {e['score']}{why}")
    return "\n".join(lines)


def _backlog_approx(*, round_no: int) -> str:
    """尽力从 Gitea 拉带 round-N 的历史票作参考；失败则空。不阻塞预览。"""
    try:
        import urllib.request

        remote = os.popen(f"git -C {HARNESS} remote get-url origin").read().strip()
        m = re.search(r"://([^:]+):([^@]+)@([^/]+)/([^/]+)/([^.]+)", remote)
        if not m:
            return "（无 Gitea backlog 快照；本预览主要依赖体感+runtime）"
        _, tok, host, owner, repo = m.groups()
        url = (
            f"http://{host}/api/v1/repos/{owner}/{repo}/issues"
            f"?state=all&limit=50&type=issues"
        )
        req = urllib.request.Request(url, headers={"Authorization": f"token {tok}"})
        with urllib.request.urlopen(req, timeout=15) as r:
            issues = json.loads(r.read())
        label = f"round-{round_no}"
        picked = []
        for i in issues:
            labs = [x["name"] for x in (i.get("labels") or [])]
            # 截至该轮：本轮标签，或更早轮次里仍可能积压的 triaged/RFC
            if label in labs or (
                round_no > 1
                and any(f"round-{k}" in labs for k in range(1, round_no + 1))
                and ("triaged" in labs or "RFC" in labs or "needs-info" in labs)
            ):
                if any(f"round-{k}" in labs for k in range(1, round_no + 1)):
                    picked.append(i)
        # 去重：只保留 round<=round_no
        filtered = []
        for i in picked:
            labs = [x["name"] for x in (i.get("labels") or [])]
            rounds = [int(x.split("-")[1]) for x in labs if x.startswith("round-")]
            if rounds and max(rounds) <= round_no:
                filtered.append(i)
        if not filtered:
            return "（该轮附近无带 round 标签的历史 issue；以体感+runtime 为主）"
        return "\n".join(
            f"- #{i['number']} [{','.join(l['name'] for l in i.get('labels') or [])}] "
            f"{i['title']}\n  {(i.get('body') or '')[:350]}"
            for i in sorted(filtered, key=lambda x: x["number"])
        )
    except Exception as exc:  # noqa: BLE001
        return f"（backlog 拉取失败：{exc}；以体感+runtime 为主）"


def _run_round(*, round_no: int, cumulative: list[dict]) -> dict:
    os.environ["SANDBOX_WORK_DIR"] = str(HARNESS.resolve())
    # 让 runtime_agg「最近 N」≈ 截至本轮的累计局数
    runtime = format_runtime_agg(
        aggregate_runtime(
            store=STORE,
            harness_repo=HARNESS,
            recent_n=len(cumulative),
        )
    )
    backlog = _backlog_approx(round_no=round_no)
    trend = _format_trend(cumulative)

    from nexau import Agent, AgentConfig

    cfg = AgentConfig.from_yaml(config_path=AGENT_DEF / "agent.yaml")
    # 预览限迭代，避免单轮拖太久
    cfg.max_iterations = int(os.environ.get("DIVERGENT_PREVIEW_ITERS", "80"))
    agent = Agent(config=cfg)
    msg = (
        f"这是第 {round_no}/5 轮结束后的信号快照（历史回放预览，不入库）。"
        "你是 divergent PM：从交互里挖用户可感知的产品机会；与 synthesize 同构输入。\n"
        "先按需读 MANUAL / 时间线核对，再用 complete_task 交 JSON 数组。\n\n"
        f"## 已 triaged backlog（尽力还原至 round-{round_no}）\n{backlog}\n\n"
        f"## 体感曲线（截至本轮累计 {len(cumulative)} 局）\n{trend}\n\n"
        f"## 运行时行为聚合\n{runtime}\n"
    )
    with bind_session_store(STORE):
        out = agent.run(message=msg)
    text = out if isinstance(out, str) else str(out)
    # unwrap complete_task envelope if any
    node: object = text
    for _ in range(4):
        if not isinstance(node, str):
            break
        try:
            node = json.loads(node)
        except (ValueError, TypeError):
            break
    if isinstance(node, dict):
        output = node.get("output")
        result = output.get("result") if isinstance(output, dict) else None
        if isinstance(result, str):
            text = result
        elif isinstance(result, list | dict):
            text = json.dumps(result, ensure_ascii=False)

    proposals = None
    m = re.search(r"```json\s*(.*?)\s*```", text, re.S)
    raw = m.group(1) if m else text
    try:
        # find top-level array
        start = raw.find("[")
        end = raw.rfind("]")
        if start >= 0 and end > start:
            proposals = json.loads(raw[start : end + 1])
    except (ValueError, TypeError):
        proposals = None

    return {
        "round": round_no,
        "n_sessions_cumulative": len(cumulative),
        "score_avg_round": round(
            sum(e["score"] for e in ROUNDS[round_no - 1]) / len(ROUNDS[round_no - 1]), 2
        ),
        "raw": text[:12000],
        "proposals": proposals if isinstance(proposals, list) else [],
        "parse_ok": isinstance(proposals, list),
    }


def main() -> int:
    if not (AGENT_DEF / "agent.yaml").is_file():
        raise SystemExit(f"缺 agent 定义：{AGENT_DEF}")
    if not HARNESS.is_dir():
        raise SystemExit(f"缺 harness：{HARNESS}")

    results = []
    cumulative: list[dict] = []
    for i, chunk in enumerate(ROUNDS, start=1):
        cumulative.extend(chunk)
        print(f"\n======== divergent PM preview round {i}/5 (cumulative={len(cumulative)}) ========")
        row = _run_round(round_no=i, cumulative=list(cumulative))
        results.append(row)
        props = row["proposals"]
        print(f"parse_ok={row['parse_ok']} n={len(props)}")
        for j, p in enumerate(props, 1):
            title = p.get("title") if isinstance(p, dict) else p
            direction = ""
            if isinstance(p, dict):
                direction = (p.get("fields") or {}).get("方向", "")
            print(f"  {j}. {title}")
            if direction:
                print(f"     方向: {direction[:160]}")
        OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"saved → {OUT}")

    print("\n=== DONE ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

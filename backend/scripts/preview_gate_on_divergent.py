#!/usr/bin/env python3
"""用已落盘的 divergent 5 轮预览结果，按轮模拟 gate（真 LLM，不写 Gitea）。

每轮：把该轮提案（最多 3 条，对齐生产硬顶）建成 FakeTracker 上的 divergent 候选，
再跑 Designer.gate_once；hold 跨轮积压。结果写入 data/gate_preview_by_round.json。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

from auto_designer.designer.designer import Designer
from auto_designer.designer.issue_schema import (
    DIVERGENT,
    GATE_DROPPED,
    RFC_LABEL,
    TRIAGED,
    round_label,
)
from auto_designer.models import IssueDraft
from auto_designer.tracker.fake import FakeTracker
from auto_designer.user.session_store import SessionStore

PREVIEW = ROOT / "data" / "divergent_pm_preview_by_round.json"
OUT = ROOT / "data" / "gate_preview_by_round.json"
HARNESS = ROOT / "data" / "harness_sandbox" / "harness_repo"
AGENT = ROOT / "agent_defs" / "designer"
STORE = SessionStore(ROOT / "data" / "sessions")
MAX_NEW = 3


def _priority_rank(p: dict) -> int:
    raw = str(p.get("priority") or "P3").upper()
    order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    return order.get(raw, 3)


def _to_body(p: dict) -> str:
    """把预览里杂乱 schema 压成可读 body（gate 主要看标题+正文）。"""
    chunks = [f"### 标题\n{p.get('title', '')}"]
    for key in (
        "user_problem",
        "user_need",
        "user_signal",
        "signal",
        "insight",
        "opportunity",
        "why_user_cares",
        "why_now",
        "user_perception",
        "expected_user_value",
        "mvp",
        "product_surface",
        "design_direction",
        "design_directions",
        "success_metrics",
        "evidence",
        "signals",
    ):
        if key not in p or p[key] in (None, "", [], {}):
            continue
        val = p[key]
        if isinstance(val, list):
            text = "\n".join(f"- {x}" for x in val[:8])
        elif isinstance(val, dict):
            text = json.dumps(val, ensure_ascii=False)[:800]
        else:
            text = str(val)[:800]
        chunks.append(f"### {key}\n{text}")
    return "\n\n".join(chunks)


def _pick_new(props: list[dict]) -> list[dict]:
    ranked = sorted(props, key=_priority_rank)
    return ranked[:MAX_NEW]


def main() -> int:
    if not PREVIEW.is_file():
        raise SystemExit(f"缺预览数据：{PREVIEW}")
    rounds = json.loads(PREVIEW.read_text(encoding="utf-8"))
    tracker = FakeTracker()
    # 塞两条「synthesize 风格」RFC，看 gate 会不会把纯 runtime 重叠的候选 drop/hold
    tracker.create_issue(
        IssueDraft(
            title="预算悬崖前置为早收口，而不是超时后补状态",
            body="### 问题\n硬超时吞噬可交付\n### 根因\nentry 软收口与 max_iterations 失配\n"
            "### 方向\n机制层软收口 / 预算信号\n### 验收\ntimeout 裸断比例下降",
            labels=[RFC_LABEL],
        )
    )
    tracker.create_issue(
        IssueDraft(
            title="未完成轮要直接驱动证据收口",
            body="### 问题\n延续轮仍泛化\n### 根因\ncontinuation 只回灌上下文\n"
            "### 方向\n机制层强制证据缺口\n### 验收\n追问 diff 轮次下降",
            labels=[RFC_LABEL],
        )
    )

    designer = Designer(
        tracker,
        STORE,
        str(HARNESS),
        str(AGENT),
    )
    results: list[dict] = []
    title_by_num: dict[int, str] = {}

    for row in rounds:
        rno = int(row["round"])
        props = row.get("proposals") or []
        picked = _pick_new(props)
        created = []
        for p in picked:
            ref = tracker.create_issue(
                IssueDraft(
                    title=str(p.get("title") or "untitled"),
                    body=_to_body(p),
                    labels=[DIVERGENT, round_label(rno)],
                )
            )
            title_by_num[ref.number] = str(p.get("title") or "")
            created.append({"number": ref.number, "title": title_by_num[ref.number]})

        print(f"\n======== gate preview round {rno}/5 · new={len(created)} ========")
        for c in created:
            print(f"  + #{c['number']} {c['title'][:70]}")

        before = {
            i.number: list(i.labels)
            for i in tracker.list_open_issues()
            if DIVERGENT in i.labels
        }
        print(f"  open divergent before gate: {sorted(before)}")
        outcome = designer.gate_once()
        print(
            f"  → promote={outcome.promoted} hold={outcome.held} drop={outcome.dropped}"
        )

        open_now = {i.number: i for i in tracker.list_open_issues()}
        snap = {
            "round": rno,
            "new_candidates": created,
            "promoted": [
                {"number": n, "title": title_by_num.get(n, open_now.get(n) and open_now[n].title)}
                for n in outcome.promoted
            ],
            "held": [
                {"number": n, "title": title_by_num.get(n, "")}
                for n in outcome.held
            ],
            "dropped": [
                {"number": n, "title": title_by_num.get(n, "")}
                for n in outcome.dropped
            ],
            "open_divergent_after": [
                {"number": i.number, "title": i.title, "labels": i.labels}
                for i in tracker.list_open_issues()
                if DIVERGENT in i.labels
            ],
            "open_promoted_features": [
                {"number": i.number, "title": i.title, "labels": i.labels}
                for i in tracker.list_open_issues()
                if TRIAGED in i.labels and "feature" in i.labels and DIVERGENT not in i.labels
            ],
        }
        results.append(snap)
        OUT.write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"  saved → {OUT}")

    print("\n=== DONE ===")
    for snap in results:
        print(f"\nR{snap['round']}:")
        for x in snap["promoted"]:
            print(f"  PROMOTE #{x['number']} {x['title'][:70]}")
        for x in snap["held"]:
            print(f"  HOLD    #{x['number']} {x['title'][:70]}")
        for x in snap["dropped"]:
            print(f"  DROP    #{x['number']} {x['title'][:70]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

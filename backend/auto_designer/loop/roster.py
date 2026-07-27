"""角色编制（roster）：各类 agent 的数量，作为「后端编排」与「前端小镇房间」的单一真源。

后端 run.py 据此决定跑几个用户会话 / 几个 triager 分片 / 几个 synthesize / 几个 divergent /
owner 评审开关 / 几个开发者；前端经 /api/config 读同一份，房间容量与后端一致。默认 用户3 ·
triager1 · 设计师1 · divergent0 · owner1 · 开发者3，可用环境变量 N_USERS/N_TRIAGERS/N_DESIGNERS/
N_DIVERGENTS/N_OWNERS/N_DEVELOPERS 覆盖（非负整数）。
"""

from __future__ import annotations

import os

# role -> 默认数量。键即 /api/agents 里的 role 值，前端按此分房间。
DEFAULT_ROSTER: dict[str, int] = {
    "user": 3,
    "triager": 1,  # Spec-0029：分片数——第 k 个 triager 处理 pending[k::n]，真并行
    "designer": 1,
    "divergent": 0,  # 默认关；N_DIVERGENTS=1 开启发散 PM（discovery 轨，产出经 Owner 准入）
    "owner": 1,  # Spec-0029：唯一准入，恒 0/1——0=纯机械准入（评审段跳过），≥1 按 1 算
    "developer": 3,
}

# role -> 覆盖用环境变量名。
_ENV_KEYS: dict[str, str] = {
    "user": "N_USERS",
    "triager": "N_TRIAGERS",
    "designer": "N_DESIGNERS",
    "divergent": "N_DIVERGENTS",
    "owner": "N_OWNERS",
    "developer": "N_DEVELOPERS",
}


def _read_count(*, role: str) -> int:
    raw = os.environ.get(_ENV_KEYS[role])
    if raw is None or raw.strip() == "":
        return DEFAULT_ROSTER[role]
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_ROSTER[role]
    return value if value >= 0 else DEFAULT_ROSTER[role]


def load_roster() -> dict[str, int]:
    """返回当前编制 {user, triager, designer, developer}，环境变量覆盖默认值。"""
    return {role: _read_count(role=role) for role in DEFAULT_ROSTER}

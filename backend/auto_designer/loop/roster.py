"""角色编制（roster）：三类 agent 的数量，作为「后端编排」与「前端小镇房间」的单一真源。

后端 run.py 据此决定跑几个用户会话 / 几个开发者 / 几个创新者；前端经 /api/config 读同一份，
房间容量与后端一致。默认 用户3 · 设计师1 · 开发者3，可用环境变量 N_USERS/N_DESIGNERS/N_DEVELOPERS
覆盖（非负整数）。
"""

from __future__ import annotations

import os

# role -> 默认数量。键即 /api/agents 里的 role 值，前端按此分房间。
DEFAULT_ROSTER: dict[str, int] = {"user": 3, "designer": 1, "developer": 3}

# role -> 覆盖用环境变量名。
_ENV_KEYS: dict[str, str] = {
    "user": "N_USERS",
    "designer": "N_DESIGNERS",
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
    """返回当前编制 {user, designer, developer}，环境变量覆盖默认值。"""
    return {role: _read_count(role=role) for role in DEFAULT_ROSTER}


# ---- Spec-0020/T3：开发者领取策略配置 ----
# 前 N 个 dev 用 bug_first（保底消化用户 bug），其余 design_first（设计票优先，治设计票饿死）。
_BUG_FIRST_ENV = "N_BUG_FIRST_DEVS"
DEFAULT_BUG_FIRST_DEVS = 1


def load_dev_pick_policies(*, n_developers: int) -> list[str]:
    """按编制返回每个 dev 的领取策略（长度 = n_developers，前段 bug_first 其余 design_first）。

    N_BUG_FIRST_DEVS 覆盖默认 1：0 → 全 design_first；≥编制 → 截断为全 bug_first；
    负数/非整数 → 回落默认。n_developers=0 返回空列表。
    """
    raw = os.environ.get(_BUG_FIRST_ENV)
    n_bug_first = DEFAULT_BUG_FIRST_DEVS
    if raw is not None and raw.strip() != "":
        try:
            value = int(raw)
        except ValueError:
            value = -1
        if value >= 0:
            n_bug_first = value
    n_bug_first = min(n_bug_first, max(0, n_developers))
    return ["bug_first"] * n_bug_first + ["design_first"] * (n_developers - n_bug_first)

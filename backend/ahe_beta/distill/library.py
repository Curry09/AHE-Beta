"""PersonaLibrary（spec-0006/T1）：persona 卡库的最小读写 + 契约约束校验。

一个库文件（JSON）承载多条「6 维行为卡」记录；卡 schema 的唯一公共契约见
tools/persona-distill/card-schema.md。库本身是纯数据存取：

- 读侧对未知键**前向兼容**（忽略不报错，原样保留），便于 schema 演化（Postel 法则）。
- `validate_card` 是**独立的严格校验门**（采集/入库时显式调用、测试用），与存取的宽容解耦：
  断言卡只含契约允许的顶层键（从而不含任何 benchmark/轨迹派生字段）、D5.area ∈ 受控词表。

卡 → sim 维度的注入映射（grounded 覆盖派生）不在此处，归 0006/T2 card_to_persona。
"""

from __future__ import annotations

import json
from pathlib import Path

# card-schema.md「D5.area 受控词表」单一真源的代码副本（单 token）。
D5_AREA_VOCAB: frozenset[str] = frozenset(
    {
        "web-backend",
        "web-frontend",
        "scientific-computing",
        "data-viz",
        "ml-ai",
        "data-analysis",
        "dev-tooling",
        "data-eng",
        "infra-devops",
        "databases",
        "systems-runtime",
        "security",
        "mobile",
        "cross-stack",
    }
)

# card-schema.md 卡记录允许的顶层键。白名单即「不含 benchmark/轨迹派生字段」的实现：
# 任何非契约字段（如 benchmark 分数、轨迹特征）都会落在白名单外被 validate_card 拒。
ALLOWED_CARD_KEYS: frozenset[str] = frozenset(
    {
        "id",
        "authenticity",
        "era",
        "dimensions",
        "provenance",
        "behavioral_prediction",
        # 被拒卡（未入库）记录：
        "reject_reason",
        "action",
    }
)


def validate_card(record: dict) -> None:
    """按 card-schema.md 校验一条卡记录；不符合则抛 ValueError。

    只做契约级的硬约束（白名单 + D5.area 受控词表），不替代抽取 skill 的真实性门。
    """
    extra = set(record) - ALLOWED_CARD_KEYS
    if extra:
        raise ValueError(
            f"卡记录含契约外字段 {sorted(extra)}（疑似 benchmark/轨迹派生字段）；"
            f"允许的顶层键见 card-schema.md：{sorted(ALLOWED_CARD_KEYS)}"
        )
    dims = record.get("dimensions")
    if isinstance(dims, dict):
        d5 = dims.get("D5_domain")
        if isinstance(d5, dict) and "area" in d5:
            area = d5["area"]
            if area not in D5_AREA_VOCAB:
                raise ValueError(
                    f"D5.area={area!r} 不在受控词表内（须为单 token）；见 card-schema.md：{sorted(D5_AREA_VOCAB)}"
                )


class PersonaLibrary:
    """单个 JSON 文件承载多条卡记录的最小库。单进程 MVP，不处理并发写竞态。"""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def load(self) -> list[dict]:
        """读全库；文件不存在视为空库（合法初始态）。"""
        if not self._path.exists():
            return []
        data = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError(f"persona 库文件 {self._path} 顶层应为卡记录数组")
        return data

    def get(self, persona_id: str) -> dict:
        """按 id 取一条卡；不存在抛 KeyError。"""
        for record in self.load():
            if record.get("id") == persona_id:
                return record
        raise KeyError(persona_id)

    def add(self, record: dict) -> None:
        """追加一条卡记录并落盘（存取宽容；严格校验请显式调 validate_card）。"""
        records = self.load()
        records.append(record)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

"""SeedLibrary（spec-0010/T1）：种子卡库的最小读写 + 契约约束校验。

一个库文件（JSON）承载多条 source-agnostic 种子卡记录；卡 schema 的唯一公共契约见
tools/seed-distill/seed-card-schema.md。库本身是纯数据存取（与 0006 的 PersonaLibrary 同构）：

- 读侧对未知键**前向兼容**（忽略不报错、原样保留），便于 schema 演化（Postel 法则）。
- `validate_card` 是**独立的严格校验门**（采集/入库时显式调用、测试用），与存取的宽容解耦：
  断言卡只含契约允许的顶层键（从而不含任何 benchmark/轨迹派生字段）、`source.not_in_benchmark`
  恒为真（防 benchmark 污染）、domain ∈ 受控词表、capability_probed ⊆ 能力分类法。

held-out 字段（oracle/test_cmd/gates）随卡采集保留；到 SeedScenario 的注入映射（含 held-out
字段剥离）不在此处，归 0010/T2 seed_adapter.card_to_seed。
"""

from __future__ import annotations

import json
from pathlib import Path

# seed-card-schema.md「domain 受控词表」单一真源的代码副本；与 persona D5.area 共享同一 14 token。
DOMAIN_VOCAB: frozenset[str] = frozenset(
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

# seed-card-schema.md「capability 分类法」单一真源的代码副本。
CAPABILITY_TAXONOMY: frozenset[str] = frozenset(
    {
        "intent-inference",
        "correctness-edgecase",
        "long-output",
        "tool-use-verification",
        "scope-discipline",
        "env-setup",
        "error-recovery",
        "explanation-teaching",
    }
)

# seed-card-schema.md 卡记录允许的顶层键。白名单即「不含 benchmark/轨迹派生字段」的实现：
# 任何非契约字段（如 benchmark 分数、轨迹特征）都会落在白名单外被 validate_card 拒。
ALLOWED_CARD_KEYS: frozenset[str] = frozenset(
    {
        "id",
        "source",
        "task",
        "domain",
        "capability_probed",
        "difficulty",
        "scope",
        "autonomy_required",
        "oracle",
        "env",
        "pairing_constraints",
        "gates",
        "provenance",
        # 被拒卡（未入库）记录：
        "reject_reason",
        "action",
    }
)


def validate_card(record: dict) -> None:
    """按 seed-card-schema.md 校验一条种子卡记录；不符合则抛 ValueError。

    Spec-0010/T1: 只做契约级硬约束（白名单 + not_in_benchmark 门 + domain/capability 受控），
    不替代抽取 skill 的两道门（oracle 门 + harbor 可复现门）。被拒卡（含 reject_reason，
    不进种子库）不在此门内——只校验拟入库的真实卡。
    """
    # 1. 白名单：任何契约外顶层键（疑似 benchmark/轨迹派生）即拒。
    extra = set(record) - ALLOWED_CARD_KEYS
    if extra:
        raise ValueError(
            f"卡记录含契约外字段 {sorted(extra)}（疑似 benchmark/轨迹派生字段）；"
            f"允许的顶层键见 seed-card-schema.md：{sorted(ALLOWED_CARD_KEYS)}"
        )
    # 2. 非 benchmark 门（契约铁律 #3）：source.not_in_benchmark 恒为真。
    source = record.get("source")
    if isinstance(source, dict):
        if source.get("not_in_benchmark") is not True:
            raise ValueError(
                "卡 source.not_in_benchmark 必须为真（防 benchmark 污染训练目标）；"
                "见 seed-card-schema.md 铁律 #3"
            )
    # 3. domain ∈ 受控词表（单一 token）。
    domain = record.get("domain")
    if domain is not None and domain not in DOMAIN_VOCAB:
        raise ValueError(
            f"domain={domain!r} 不在受控词表内（须为单 token）；见 seed-card-schema.md：{sorted(DOMAIN_VOCAB)}"
        )
    # 4. capability_probed ⊆ 能力分类法。
    caps = record.get("capability_probed")
    if caps is not None:
        unknown = set(caps) - CAPABILITY_TAXONOMY
        if unknown:
            raise ValueError(
                f"capability_probed 含分类法外能力 {sorted(unknown)}；"
                f"见 seed-card-schema.md：{sorted(CAPABILITY_TAXONOMY)}"
            )


class SeedLibrary:
    """单个 JSON 文件承载多条种子卡记录的最小库。单进程 MVP，不处理并发写竞态。"""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def load(self) -> list[dict]:
        """读全库；文件不存在视为空库（合法初始态）。"""
        if not self._path.exists():
            return []
        data = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(data, list):
            raise ValueError(f"种子卡库文件 {self._path} 顶层应为卡记录数组")
        return data

    def get(self, seed_id: str) -> dict:
        """按 id 取一条卡；不存在抛 KeyError。"""
        for record in self.load():
            if record.get("id") == seed_id:
                return record
        raise KeyError(seed_id)

    def add(self, record: dict) -> None:
        """追加一条卡记录并落盘（存取宽容；严格校验请显式调 validate_card）。"""
        records = self.load()
        records.append(record)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            json.dumps(records, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

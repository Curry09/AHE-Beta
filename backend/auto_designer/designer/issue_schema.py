# Spec-0025/T1：平台层标准 issue schema——每 kind 声明式字段，分 USER/TRIAGE 区，校验 + 确定性渲染。
"""标准 issue 格式的单一真源（平台层，dev 够不着——issue 格式是平台制品，不可被 harness 进化改动）。

**LLM 只填字段值，格式由 render 保证**——不靠 LLM 自觉对齐格式，也不靠 Gitea 表单（issue 全程走 API
创建，Gitea 的 ISSUE_TEMPLATE 只作用于 Web UI，校验不到 API）。字段按 kind 声明，且分两区：

- **USER 区**：用户可见字段，由用户 sim 的 persona 在提 issue 时填（它亲历会话、知道症状，但看不到代码）。
- **TRIAGE 区**：需读 harness 代码 / god-view 轨迹才能定位的字段，由 triage agent 填。

`validate(kind, fields, section)` 校验必填在；`render(kind, fields, section)` 渲染 `### <label>` 分节
markdown（单一布局，前端 + 回读一套解析器）。加新 kind 只增 SCHEMAS 声明、不改 validate/render 逻辑。
"""

from __future__ import annotations

from dataclasses import dataclass

USER = "user"
TRIAGE = "triage"

# 优先级枚举（单一真源）。值由编排层按体感影响 + runtime_agg 频率**机制派生**（Spec-0025/T6），
# 非 triage agent 填——故不列为 body 字段，只作标签枚举供 dispatch/前端用。
PRIORITIES = ("P0", "P1", "P2", "P3")

# ---- triage 工作流标签（平台层单一真源，供 sim/triage/dev/web 共用）----
NEEDS_TRIAGE = "needs-triage"  # 用户 sim 新产、待 triage（可领集合排除）
TRIAGED = "triaged"  # triage 完成、dev 可领
REJECTED = "rejected"  # triage 驳回（带原因关闭，可领集合排除）
NEEDS_INFO = "needs-info"  # triage 判信息不足（带原因关闭，可领集合排除）
RFC_LABEL = "RFC"  # synthesize agent 产的结构综合提案（凌驾 type，dev 可领、最高预算）
SUPERSEDED = "superseded"  # 被 RFC 取代的局部 issue（可领集合排除；具体 #号记 comment）


def round_label(round_no: int) -> str:
    """轮号标签：`round-<N>`。用户 issue 盖它，供增量 triage / 观测曲线按轮计数。"""
    return f"round-{int(round_no)}"


@dataclass(frozen=True)
class Field:
    """一个字段的声明：机器 key + 展示 label + 归属区（user/triage）+ 是否必填。"""

    key: str
    label: str
    section: str
    required: bool = True


# 每 kind 的字段声明；元组顺序即 render 顺序。RFC 在标签层凌驾 type（consolidate 局部 issue），
# 在 schema 层只是又一个 kind（有自己的结构字段，不套 bug 的复现模板）。
SCHEMAS: dict[str, tuple[Field, ...]] = {
    "bug": (
        Field("repro", "复现步骤", USER),
        Field("expected", "期望行为", USER),
        Field("actual", "实际行为", USER),
        Field("root_cause", "根因区域", TRIAGE),
        Field("boundary", "边界", TRIAGE),
        Field("acceptance", "验收", TRIAGE),
    ),
    "feature": (
        Field("background", "背景", USER),
        Field("goal", "目标", USER),
        Field("scenario", "场景", USER),
        Field("boundary", "边界", TRIAGE),
        Field("deliverable", "交付物", TRIAGE),
        Field("acceptance", "验收", TRIAGE),
    ),
    # chore/document 起步字段精简（harness 进化场景里少见，先占位、可扩）。
    "chore": (
        Field("goal", "目标", USER),
        Field("boundary", "边界", TRIAGE, required=False),
        Field("acceptance", "验收", TRIAGE),
    ),
    "document": (
        Field("goal", "目标", USER),
        Field("acceptance", "验收", TRIAGE, required=False),
    ),
    # RFC：结构性综合提案（synthesize agent 产），字段独立、全在 triage 侧（由 agent 填）。
    "rfc": (
        Field("problem", "问题", TRIAGE),
        Field("root_cause", "根因", TRIAGE),
        Field("related", "涉及 issue", TRIAGE),
        Field("direction", "方向", TRIAGE),
        Field("acceptance", "验收", TRIAGE),
    ),
}

# 用户 sim 侧可产的 kind（RFC 由 synthesize agent 产、不由用户提）。
USER_KINDS = ("bug", "feature", "chore", "document")


def kinds() -> tuple[str, ...]:
    """全部已声明 kind。"""
    return tuple(SCHEMAS)


def fields_of(*, kind: str, section: str | None = None) -> tuple[Field, ...]:
    """取某 kind 的字段（section 限定只取某区，None 取全部，保持声明顺序）；未知 kind 返回空。"""
    schema = SCHEMAS.get(kind)
    if schema is None:
        return ()
    if section is None:
        return schema
    return tuple(f for f in schema if f.section == section)


def validate(*, kind: str, fields: dict, section: str | None = None) -> list[str]:
    """校验：未知 kind / 缺必填 / 空值。section 限定只查某区（None 查全部）。返回错误列表（空=通过）。

    分区校验支持"两端各填各的"：T2 用户侧 validate(section='user')，T3 triage 侧 validate(section='triage')。
    """
    if kind not in SCHEMAS:
        return [f"未知 issue kind: {kind!r}（须属 {tuple(SCHEMAS)}）"]
    errors: list[str] = []
    for f in SCHEMAS[kind]:
        if section is not None and f.section != section:
            continue
        if not f.required:
            continue
        val = fields.get(f.key)
        if val is None or (isinstance(val, str) and not val.strip()):
            errors.append(f"缺必填字段 {f.key}（{f.label}，{f.section} 区）")
    return errors


# 未填字段的渲染占位（T2 建 issue 时 triage 区尚空 → 占位；triage 补后再 render 覆盖）。
_PLACEHOLDER = "_（待补）_"


def render(*, kind: str, fields: dict, section: str | None = None) -> str:
    """按 schema 声明顺序渲染 `### <label>\\n\\n<value>` 分节 markdown（单一布局）。

    section 限定只渲染某区：T2 body = render(section='user')；T3 triage 补充 = render(section='triage')。
    缺的字段渲染占位符（不报错——用户填得潦草时留白待 triage）。未知 kind 抛 ValueError。
    """
    schema = SCHEMAS.get(kind)
    if schema is None:
        raise ValueError(f"未知 issue kind: {kind!r}（须属 {tuple(SCHEMAS)}）")
    parts: list[str] = []
    for f in schema:
        if section is not None and f.section != section:
            continue
        val = fields.get(f.key)
        text = str(val).strip() if val is not None and str(val).strip() else _PLACEHOLDER
        parts.append(f"### {f.label}\n\n{text}")
    return "\n\n".join(parts)

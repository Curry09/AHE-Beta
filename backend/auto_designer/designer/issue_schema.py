# Spec-0025/T1：平台层标准 issue schema——每 kind 声明式字段，分 USER/TRIAGE 区，校验 + 确定性渲染。
"""标准 issue 格式的单一真源（平台层，dev 够不着——issue 格式是平台制品，不可被 harness 进化改动）。

**LLM 只填字段值，格式由 render 保证**——不靠 LLM 自觉对齐格式，也不靠 Gitea 表单（issue 全程走 API
创建，Gitea 的 ISSUE_TEMPLATE 只作用于 Web UI，校验不到 API）。

Spec-0027/T1 收敛：schema 只声明「规范化产物」字段——即 triage / synthesize agent 定位后填的字段
（根因区域/边界/验收、RFC 的 问题/根因/…），是 dev 的 Definition of Ready。用户报的 issue **body 是
自由文本**（真实 persona 不填模板），不再声明 USER 段模板（原 USER 段从未接线、已删）。契约的机器
校验交给 nexau 工具层（见 designer/agent_contract.py 由本 SCHEMAS 生成 submit 工具 input_schema）。

`validate(kind, fields)` 校验必填在；`render(kind, fields)` 渲染 `### <label>` 分节 markdown（供 triage
挂 comment / RFC body）。`section` 参数随本次收敛退化为单一值，保留仅为向后兼容。加新 kind 只增
SCHEMAS 声明、不改 validate/render 逻辑。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

USER = "user"
TRIAGE = "triage"

# 优先级枚举（单一真源，高→低）。由 **triage agent** 按严重度 × 那局体感判定（Spec-0025/T3），
# 以标签形式落库——不列为 body 字段，只作标签枚举供 dispatch / 前端徽标用。
PRIORITIES = ("P0", "P1", "P2", "P3")

# ---- 三平面标签（Spec-0029/T1：资格只看这三个词，写侧新数据只产它们）----
REPORT = "report"  # 平面1 证据：用户 sim 的原始报告（自由文本），谁都不能领
PROPOSAL = "proposal"  # 平面2 提案：一律不可领；由生成器（triage/synthesize/divergent）产出
READY = "ready"  # 平面3 工作队列：唯一可领白名单，Owner 准入后才有
# Spec-0032/T3：交付面交接令牌（OpenAgents vigil 的发现标签）。Owner 准入改打它而非直接打 ready——
# vigil `_intake` 对已带 ready 的票直接跳过、curator 依赖排序只在「本轮有新准入」时触发，Owner 直打
# ready 会把 curator 饿死；vigil 发现本标签后自己盖 ready（幂等）。读侧把它与 ready 同视为 READY 平面。
OPENAGENTS = "openagents"
# 终态标签（关闭时替换平面标签落上；写侧保证平面标签与终态标签不并存）
DECLINED = (
    "declined"  # 被驳回关闭（triage reject/needs_info、Owner decline；原因记 comment/close reason）
)
MERGED = "merged"  # 被 Designer 的 covers 吸收后合并关闭（merged-into 机器行链主票）
# provenance 标签（属性，不参与资格判定）：这条提案是谁产的
FROM_TRIAGE = "from-triage"
FROM_SYNTHESIZE = "from-synthesize"
FROM_DIVERGENT = "from-divergent"
OBSERVATION_GAP = "observation-gap"

# ---- 旧工作流标签（Spec-0025/0028 写侧已退役；保留常量供读侧映射旧数据，见 plane()）----
NEEDS_TRIAGE = "needs-triage"  # 旧：用户 sim 新产、待 triage → 映射 report
TRIAGED = "triaged"  # 旧：triage 完成、dev 可领 → 映射 ready
REJECTED = "rejected"  # 旧：triage 驳回关闭 → 终态
NEEDS_INFO = "needs-info"  # 旧：信息不足关闭 → 终态
RFC_LABEL = "RFC"  # 旧：结构综合提案、dev 可领 → 映射 ready
SUPERSEDED = "superseded"  # 旧：被 RFC 取代 → 终态
DIVERGENT = "divergent"  # 旧：产品候选不可领 → 映射 proposal
GATE_DROPPED = "gate-dropped"  # 旧：gate 丢弃关闭 → 终态


def round_label(round_no: int) -> str:
    """轮号标签：`round-<N>`。用户 issue 盖它，供增量 triage / 观测曲线按轮计数。"""
    return f"round-{int(round_no)}"


# ---- 标签 → 语义投影（平台层单一真源，供 web / metrics / dev / 前端共用）----
# issue 的 kind / 轮号 / triage 状态 / 优先级 全部只由标签决定；这里集中做投影，避免各处各写一份。

_ROUND_RE = re.compile(r"^round-(\d+)$")


def issue_kind(labels: list[str]) -> str:
    """标签 → issue kind：RFC 优先（凌驾 type），否则取首个 USER_KINDS 命中；都无则 'bug'（暂定兜底）。"""
    ls = list(labels or [])
    if RFC_LABEL in ls:
        return "rfc"
    for k in USER_KINDS:
        if k in ls:
            return k
    return "bug"


def round_of(labels: list[str]) -> int | None:
    """标签 → 轮号（`round-N` 的 N）；无则 None。"""
    for x in labels or []:
        m = _ROUND_RE.match(str(x))
        if m:
            return int(m.group(1))
    return None


def filter_current_round(items, *, round_no: int | None):
    """Keep only issues belonging to the active round.

    New issues are stamped with a ``round-N`` label.  If a collection contains
    any such labels, unlabelled issues are excluded as well: their round cannot
    be inferred safely and allowing them would reintroduce cross-round input
    leakage.  Collections made entirely of legacy, unlabelled issues are kept
    unchanged for backwards compatibility with old repositories and fixtures.
    """
    if type(round_no) is not int or round_no <= 0:
        return list(items)
    values = list(items)
    if not any(round_of(item.labels) is not None for item in values):
        return values
    return [item for item in values if round_of(item.labels) == round_no]


def filter_designer_round(items, *, round_no: int | None):
    """Include pending diagnostic proposals even when their creator omitted a round label.

    A gap from an earlier round still needs design.  A future-labelled issue must
    not enter the current round.  Callers exclude the independent PM route first.
    """
    values = list(items)
    selected = filter_current_round(values, round_no=round_no)
    seen = {item.number for item in selected}
    for item in values:
        issue_round = round_of(item.labels)
        if (
            item.number not in seen
            and OBSERVATION_GAP in item.labels
            and plane(item.labels) == PROPOSAL
            and (round_no is None or issue_round is None or issue_round <= round_no)
        ):
            selected.append(item)
            seen.add(item.number)
    return selected


def priority_of(labels: list[str]) -> str | None:
    """标签 → 优先级（P0-P3）；无则 None。多个并存取最高（PRIORITIES 已按高→低）。"""
    present = [p for p in PRIORITIES if p in (labels or [])]
    return present[0] if present else None


def triage_status(labels: list[str]) -> str | None:
    """标签 → triage 状态（单值）：越决定性者胜——驳回/待补/gate 丢弃(终态关闭) > superseded >
    divergent(候选不可领) > triaged(可执行) > needs-triage(待处理)；都无则 None。"""
    ls = list(labels or [])
    for s in (REJECTED, NEEDS_INFO, GATE_DROPPED, SUPERSEDED, DIVERGENT, TRIAGED, NEEDS_TRIAGE):
        if s in ls:
            return s
    return None


# ---- 三平面投影（Spec-0029/T1：资格判定的单一真源）----

# 终态标签（新老并集）：命中即不在任何平面。
_TERMINAL_LABELS = frozenset({DECLINED, MERGED, REJECTED, NEEDS_INFO, GATE_DROPPED, SUPERSEDED})


def plane(labels: list[str]) -> str | None:
    """标签 → 所在平面（report/proposal/ready 三值）；终态或无平面标签返回 None。

    新平面标签优先（写侧新数据只产它们）；旧数据经读侧映射：needs-triage→report、
    triaged|RFC→ready、divergent→proposal；终态（新老）先于旧映射判定（对齐旧 triage_status
    的「越决定性者胜」——旧 triaged+superseded 组合是终态、不是 ready）。

    Spec-0032/T3：`openagents`（Owner 准入的交付面交接令牌）与 `ready`（vigil 盖的执行面令牌）
    同属 READY 平面——准入一落地即计入工作队列，vigil 随后盖 ready 幂等无感（metrics funnel /
    背压告警 / 前端分组随本投影自动正确）。
    """
    ls = set(labels or [])
    if READY in ls or OPENAGENTS in ls:
        return READY
    if PROPOSAL in ls:
        return PROPOSAL
    if REPORT in ls:
        return REPORT
    if ls & _TERMINAL_LABELS:
        return None
    if DIVERGENT in ls:
        return PROPOSAL
    if TRIAGED in ls or RFC_LABEL in ls:
        return READY
    if NEEDS_TRIAGE in ls:
        return REPORT
    return None


def is_ready(*, labels: list[str], state: str) -> bool:
    """dev 可领判定（唯一白名单）：open 且在 ready 平面。新增任何流程标签都默认不可领（fail-closed）。"""
    return state == "open" and plane(labels) == READY


def is_backlog_by_labels(labels: list[str]) -> bool:
    """仅按标签判是否属「可执行 backlog」类 = 在 ready 平面（经 plane 投影，新旧标签统一口径）。
    不看开/关状态——供观测曲线按事件累计（关闭事件自会抵消）。"""
    return plane(labels) == READY


def is_executable_backlog(*, labels: list[str], state: str) -> bool:
    """某时刻是否算可执行 backlog：open 且在 ready 平面（dev 可领 / 曲线当前计数口径）。"""
    return is_ready(labels=labels, state=state)


def provenance_of(labels: list[str]) -> str | None:
    """标签 → 提案来源（from-triage/from-synthesize/from-divergent）；无则 None。"""
    for p in (FROM_TRIAGE, FROM_SYNTHESIZE, FROM_DIVERGENT):
        if p in (labels or []):
            return p
    return None


# ---- covers / merged-into 机器行（单一真源解析；covers 是 Designer 的吸收决定）----

# covers 行（提案 body 里的覆盖声明，创建时写、之后不改写）：`covers: #5 #6`，多条取最后一条。
_COVERS_LINE_RE = re.compile(r"^covers:((?:\s*#\d+)+)\s*$", re.MULTILINE)
# merged-into 行（被合并票的 comment / close reason）：`merged-into: #7`，多条取最后一条。
_MERGED_INTO_RE = re.compile(r"^merged-into:\s*#(\d+)\s*$", re.MULTILINE)


def parse_covers_line(body: str) -> list[int]:
    """body → covers 行声明的票号列表（无该行返回空；多条取最后一条）。"""
    last: str | None = None
    for m in _COVERS_LINE_RE.finditer(body or ""):
        last = m.group(1)
    if last is None:
        return []
    return [int(x) for x in re.findall(r"#(\d+)", last)]


def format_covers_line(numbers: list[int]) -> str:
    """票号列表 → covers 机器行。空列表返回空串（不写行）。"""
    nums = [int(n) for n in numbers or []]
    return f"covers: {' '.join(f'#{n}' for n in nums)}" if nums else ""


def parse_merged_into(text: str) -> int | None:
    """comment/close reason 文本 → merged-into 指向的主票号；无则 None（多条取最后一条）。"""
    last: int | None = None
    for m in _MERGED_INTO_RE.finditer(text or ""):
        last = int(m.group(1))
    return last


def format_merged_into(number: int) -> str:
    """主票号 → merged-into 机器行。"""
    return f"merged-into: #{int(number)}"


@dataclass(frozen=True)
class Field:
    """一个字段的声明：机器 key + 展示 label + 归属区（user/triage）+ 是否必填。"""

    key: str
    label: str
    section: str
    required: bool = True


# 每 kind 的字段声明；元组顺序即 render 顺序。Spec-0027/T1：只保留「规范化产物」字段（triage/RFC
# agent 填的定位字段）——用户报的 issue body 是自由文本（真实用户不填模板），不再声明 USER 段模板。
# 全部字段归 TRIAGE（section 维度随本次收敛已退化为单一值，保留仅为 validate/render 向后兼容）。
SCHEMAS: dict[str, tuple[Field, ...]] = {
    "bug": (
        Field("root_cause", "根因区域", TRIAGE),
        Field("boundary", "边界", TRIAGE),
        Field("acceptance", "验收", TRIAGE),
    ),
    "feature": (
        Field("boundary", "边界", TRIAGE),
        Field("deliverable", "交付物", TRIAGE),
        Field("acceptance", "验收", TRIAGE),
    ),
    # chore/document 起步字段精简（harness 进化场景里少见，先占位、可扩）。
    "chore": (
        Field("boundary", "边界", TRIAGE, required=False),
        Field("acceptance", "验收", TRIAGE),
    ),
    "document": (Field("acceptance", "验收", TRIAGE, required=False),),
    # RFC：结构性综合提案（synthesize agent 产），字段独立、由 agent 填。
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


def output_contract_schema() -> dict:
    """Spec-0025：triage agent 输出的 JSON Schema——供 response_format=json_schema 约束解码，让
    **本 schema 成为 agent 输出契约的单一真源**（不再靠系统提示手抄 + 解析边界打补丁认漂）。

    强制：顶层键只允许 issue/disposition/kind/priority/fields/of/reason（additionalProperties=false，
    杜绝 triage_decision/平铺 root_cause/summary 这类自创字段）；disposition ∈ 四种、kind ∈ USER_KINDS、
    priority ∈ P0-P3（enum 约束，"high" 这类吐不出来）；fields 的键 = 各 kind TRIAGE 字段的并集。
    per-kind 必填与合法性仍由 driver 的 validate 二次把关（json_schema 只锁结构，不表达 kind 条件必填）。
    """
    triage_labels: list[str] = []
    for k in USER_KINDS:
        for f in fields_of(kind=k, section=TRIAGE):
            if f.label not in triage_labels:
                triage_labels.append(f.label)
    item = {
        "type": "object",
        "properties": {
            "issue": {"type": "integer"},
            "disposition": {
                "type": "string",
                "enum": ["accept", "duplicate", "reject", "needs_info"],
            },
            "kind": {"type": "string", "enum": list(USER_KINDS)},
            "priority": {"type": "string", "enum": list(PRIORITIES)},
            "fields": {
                "type": "object",
                "properties": {lbl: {"type": "string"} for lbl in triage_labels},
                "additionalProperties": False,
            },
            "of": {"type": "integer"},
            "reason": {"type": "string"},
        },
        "required": ["issue", "disposition"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"dispositions": {"type": "array", "items": item}},
        "required": ["dispositions"],
        "additionalProperties": False,
    }


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

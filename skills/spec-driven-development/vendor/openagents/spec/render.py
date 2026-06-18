"""spec render：把源数据派生成唯一人读视图 OVERVIEW.md。

Spec-0014/T3: spec render → OVERVIEW.md

纯函数、幂等（决策 D3/D9）：同一份源数据两次 render 字节级一致。生成六块：
  1. 名词解释（读 specs_root/glossary.yaml；缺省则跳过——OVERVIEW 唯一可手工维护的源）
  2. 全局看板表（组 | NNNN/T* | 标题 | 状态 | 依赖 | 涉及文件）
  3. 跨 feature 关系图（Mermaid，按 feature 分 subgraph；depends-on 实线、relates-to 虚线标 type）
  4. 文件冲突报告（跨组 files 重叠，协作信号）
  5. 设计文件结构（所有 Task 的 files 并集铺成目录树，每个文件标注归属 Task）
  6. 每 feature 段（组内看板 + 依赖 DAG + 演化图：节点=Task 版本、按 status 着色、血缘连边）

不感知 git / GitHub（理念 10 解耦）。
"""

from __future__ import annotations

from pathlib import Path

from openagents.spec import model
from openagents.spec.model import Group, Task

# Spec-0014/T3：演化图节点按 status 着色（pending/in-progress/done/abandoned）。
_STATUS_FILL = {
    "pending": "#eeeeee",
    "in-progress": "#fff3b0",
    "done": "#b7e4c7",
    "abandoned": "#f4b8b8",
}

# Spec-0014/T3：固定标题，便于断言「四块齐全」。
_SYNOPSIS_HEADING = "## 总览"
_BOARD_HEADING = "## 全局看板"
_RELATION_HEADING = "## 跨 feature 关系图"
_CONFLICT_HEADING = "## 文件冲突报告"
_TREE_HEADING = "## 设计文件结构"
_GLOSSARY_HEADING = "## 名词解释"
_FEATURE_HEADING = "## 各 feature 详情"

# 顶部「如何读」导语：先给只看 OVERVIEW 的读者一个入口与主线，再进入看板/图，
# 避免一上来就是宽表 + Mermaid 的机器视角。静态文本，保持 render 确定性。
_HOWTO = (
    "## 如何读这份文档\n"
    "\n"
    "本文件是所有 spec 的**全局看板**，由各组 `tasks/T*.yaml` 自动汇总，偏索引视角。"
    "想读某一组的完整方案，请点进该组的 `summary.md`（每个 feature 段开头有链接）。\n"
    "\n"
    "阅读顺序建议：不熟术语先看**名词解释** → 看**全局看板**掌握全部任务与状态 → 看"
    "**跨 feature 关系图**了解依赖 → 看**设计文件结构**掌握落盘布局与文件归属 → 在"
    "**各 feature 详情**里逐组读导语与任务一览。"
)


def render(*, specs_root: Path) -> str:
    """Render the full OVERVIEW.md text from a specs tree (pure, idempotent).

    Spec-0014/T3：纯函数返回全文；空仓库返回仅含四块标题的骨架，不报错。
    """
    groups = model.load_all(specs_root=specs_root)
    blocks = [
        "# Spec 总览（OVERVIEW）",
        "> 本文件由 `spec render` 自动生成，请勿手工编辑（Spec-0014/T3）。",
        _render_synopsis(groups=groups),
        _HOWTO,
        _render_glossary(specs_root=specs_root),
        _render_board(groups=groups),
        _render_relations(groups=groups),
        _render_conflicts(groups=groups),
        _render_file_tree(groups=groups),
        _render_features(groups=groups),
    ]
    # 统一以单个换行连接、整体以换行结尾，保证确定性。
    return "\n\n".join(blocks).rstrip("\n") + "\n"


def write_overview(*, specs_root: Path) -> Path:
    """Render and write docs/specs/OVERVIEW.md, returning its path.

    Spec-0014/T3：render + 落盘到 specs_root/OVERVIEW.md。
    """
    path = specs_root / "OVERVIEW.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(specs_root=specs_root), encoding="utf-8")
    return path


# ── 每组人读方案 summary.md（给人看的「总的方案」）──
# OVERVIEW.md 是全局看板（表 + Mermaid），偏机器/索引视角；summary.md 是单个组的
# 可读方案，把该组 metadata + 各 Task 的 prose（summary/motivation/design…）顺成一页
# 给人通读。同为派生视图：纯函数、幂等、勿手改。源仍是 tasks/T*.yaml。

# prose 字段在 summary.md 中的人读小标题与渲染顺序（结构化的 files 单列）。
_SUMMARY_SECTIONS: tuple[tuple[str, str], ...] = (
    ("summary", "做什么"),
    ("motivation", "为什么"),
    ("scope", "范围"),
    ("design", "整体设计"),
    ("interface", "接口"),
    ("tradeoffs", "取舍"),
    ("acceptance", "验收标准"),
    ("tests", "测试"),
    ("references", "参考"),
    ("open_questions", "待解问题"),
)


def render_group_summary(*, group: Group) -> str:
    """Render one group's human-readable plan (summary.md) from its YAML (pure, idempotent).

    把组标题/issue + 组内 DAG + 每个当前版 Task 的 prose 顺成一页可读方案。空字段跳过，
    无 Task 给占位。不含时间戳等非确定量，保证两次 render 字节级一致。
    """
    title = group.metadata.title or group.metadata.slug
    blocks = [
        f"# {group.number} {title}",
        (
            "> 本文件由 `spec render` 自动生成，请勿手工编辑。\n"
            f"> 内容来源：本组 `metadata.yaml` 与 `tasks/T*.yaml`（关联 issue #{group.metadata.issue}）。"
        ),
    ]
    # 组级导语（overview）置于任务编排之前：先讲清本组在闭环中的位置、交付什么、数据流脊柱，
    # 再进入逐任务细节，避免读者一上来就陷进 T1…Tn 的依赖图（修复「summary 云里雾里」）。
    if group.metadata.overview.strip():
        blocks.append("## 总览\n\n" + group.metadata.overview.strip())
    blocks.append(_summary_orchestration(group=group))
    if group.tasks:
        blocks.append("## 各任务方案")
        for task in group.tasks:
            blocks.append(_summary_task(task=task))
    return "\n\n".join(blocks).rstrip("\n") + "\n"


def write_group_summaries(*, specs_root: Path) -> list[Path]:
    """Render and write each group's summary.md, returning the written paths (sorted).

    summary.md 落在各组目录内（`<NNNN-slug>/summary.md`），与该组源数据同处一处。
    组目录名按规范为 `<number>-<slug>`（由 `spec new` 建立）。
    """
    written: list[Path] = []
    for group in model.load_all(specs_root=specs_root):
        group_dir = specs_root / f"{group.number}-{group.metadata.slug}"
        if not group_dir.is_dir():
            # slug 与目录名不一致（异常态）则跳过，不去猜目录。
            continue
        path = group_dir / "summary.md"
        path.write_text(render_group_summary(group=group), encoding="utf-8")
        written.append(path)
    return written


def _summary_orchestration(*, group: Group) -> str:
    """summary.md「任务编排」段：组内依赖 DAG + 一个轻量任务表。"""
    lines = ["## 任务编排", "", _render_group_dag(group=group), ""]
    if not group.tasks:
        lines.append("（本组暂无任务）")
        return "\n".join(lines).rstrip("\n")
    lines.extend(["| 任务 | 标题 | 优先级 | 状态 | 依赖 |", "|----|----|----|----|----|"])
    for task in group.tasks:
        deps = ", ".join(task.depends_on) or "—"
        lines.append(
            f"| {task.id} | {_cell(task.title)} | {task.priority} | {task.status} | {deps} |"
        )
    return "\n".join(lines)


def _summary_task(*, task: Task) -> str:
    """summary.md 单个 Task 段：标题行 + 涉及文件 + 各 prose 小节（空的跳过）。"""
    lines = [f"### {task.id} · {_cell(task.title)}（{task.priority} / {task.status}）"]
    if task.files:
        lines.append("")
        lines.append("**涉及文件**")
        lines.append("")
        lines.extend(f"- `{path}`" for path in task.files)
    for attr, heading in _SUMMARY_SECTIONS:
        text = getattr(task, attr).strip()
        if not text:
            continue
        lines.append("")
        lines.append(f"**{heading}**")
        lines.append("")
        lines.append(text)
    return "\n".join(lines)


def _render_synopsis(*, groups: list[Group]) -> str:
    """块 0：脉络总览——开篇用一行点题 + 逐组「编号 标题 — 导语首句」，

    让读者在看板/关系图之前先抓住整条故事线：每组按编号递进，导语首句已点明各自定位，
    串起来即一条可读脉络。内容全部派生自各组 metadata（标题 + overview 首句），不在通用渲染器里
    硬编码任何项目剧情，随 spec 演化自动保持正确。
    """
    lines = [_SYNOPSIS_HEADING, ""]
    if not groups:
        lines.append("（暂无 spec 组）")
        return "\n".join(lines)
    lines.append(
        "本仓需求按**组（feature）**拆分、按编号递进。下面一句话给出每组定位，串起整条脉络；"
    )
    lines.append("依赖与衔接见后续「跨 feature 关系图」，单组完整方案见各组 `summary.md`。")
    lines.append("")
    for group in groups:
        title = group.metadata.title or group.metadata.slug
        gist = _one_line(text=group.metadata.overview)
        tail = f" — {gist}" if gist else ""
        lines.append(f"- **{group.number} {_cell(title)}**{tail}")
    return "\n".join(lines)


def _render_glossary(*, specs_root: Path) -> str:
    """块 0：名词解释——读 specs_root/glossary.yaml，按 category 分段列术语与解释。

    glossary.yaml 是 OVERVIEW 中唯一可手工维护的源（其余块均派生自 Task）；文件缺省即跳过本块，
    不报错。category 按首次出现顺序成段；段内术语保持源顺序，便于逻辑聚类（非字典序）。
    """
    path = specs_root / "glossary.yaml"
    if not path.is_file():
        return _GLOSSARY_HEADING + "\n\n（暂无名词表 `glossary.yaml`）"
    data = model.load_yaml(path=path) or {}
    terms = data.get("terms") or []

    lines = [_GLOSSARY_HEADING, ""]
    if not terms:
        lines.append("（`glossary.yaml` 暂无 terms）")
        return "\n".join(lines)
    lines.append(
        "> 本仓共享术语表，英文优先；本块来源 `glossary.yaml`（手工维护），改名词解释改该文件后 re-render。"
    )

    # category 按首次出现顺序成段；段内保持源顺序。
    order: list[str] = []
    grouped: dict[str, list[tuple[str, str]]] = {}
    for entry in terms:
        term = str(entry.get("term", "")).strip()
        if not term:
            continue
        category = str(entry.get("category", "")).strip()
        definition = str(entry.get("def", "")).strip()
        if category not in grouped:
            order.append(category)
            grouped[category] = []
        grouped[category].append((term, definition))
    for category in order:
        lines.append("")
        if category:
            lines.append(f"### {category}")
            lines.append("")
        for term, definition in grouped[category]:
            tail = f" — {_cell(definition)}" if definition else ""
            lines.append(f"- **{_cell(term)}**{tail}")
    return "\n".join(lines)


def _render_board(*, groups: list[Group]) -> str:
    """块 1：全局看板表，每行一个当前版 Task。

    只保留「组/任务/标题/状态/依赖」五列以便横向扫读；涉及文件清单会把单元格撑得过宽，
    属于深读信息，留给各组 summary.md 的「涉及文件」段，不进全局看板。
    """
    lines = [
        _BOARD_HEADING,
        "",
        "| 组 | 任务 | 标题 | 状态 | 依赖 |",
        "|----|----|----|----|----|",
    ]
    for group in groups:
        for task in group.tasks:
            qid = model.qualified_id(group=group.number, task_id=task.id)
            deps = ", ".join(task.depends_on) or "—"
            lines.append(
                f"| {group.number} | {qid} | {_cell(task.title)} | {task.status} | {deps} |"
            )
    return "\n".join(lines)


def _render_relations(*, groups: list[Group]) -> str:
    """块 2：跨 feature 关系图（Mermaid，subgraph/feature；depends-on 实线、relates-to 虚线）。"""
    # 图例置于图前，帮不熟 Mermaid 的读者理解连线：实线=依赖，虚线=关联（标关联类型）。
    lines = [
        _RELATION_HEADING,
        "",
        "> 图例：实线箭头 `A --> B` 表示 A **依赖** B；虚线箭头 `A -.type.-> B` 表示 A 与 B **关联**（type 为关联类型）。",
        "",
        "```mermaid",
        "graph LR",
    ]
    current_ids = {
        model.qualified_id(group=g.number, task_id=t.id) for g in groups for t in g.tasks
    }
    # 1. 每个 feature 一个 subgraph，内含其当前版 Task 节点。
    for group in groups:
        lines.append(f"    subgraph G{group.number}[{group.number} {group.metadata.slug}]")
        for task in group.tasks:
            qid = model.qualified_id(group=group.number, task_id=task.id)
            lines.append(f'        {_node(qid)}["{task.id} {_cell(task.title)}"]')
        lines.append("    end")
    # 2. depends-on 实线边（解析为限定 ID；只连存在节点）。
    for group in groups:
        for task in group.tasks:
            src = model.qualified_id(group=group.number, task_id=task.id)
            for ref in task.depends_on:
                dst = _resolve(ref=ref, group=group.number)
                if dst in current_ids:
                    lines.append(f"    {_node(src)} --> {_node(dst)}")
    # 3. relates-to 虚线边（标 type）。
    for group in groups:
        for task in group.tasks:
            src = model.qualified_id(group=group.number, task_id=task.id)
            for rel in task.relates_to:
                dst = _resolve(ref=rel.ref, group=group.number)
                if dst in current_ids:
                    lines.append(f"    {_node(src)} -.{rel.type}.-> {_node(dst)}")
    lines.append("```")
    return "\n".join(lines)


def _render_conflicts(*, groups: list[Group]) -> str:
    """块 3：文件冲突报告——同一文件被 ≥2 个组占用（协作信号）。"""
    # file -> 占用它的组编号集合。
    owners: dict[str, set[str]] = {}
    for group in groups:
        for task in group.tasks:
            for path in task.files:
                owners.setdefault(path, set()).add(group.number)

    conflicts = {path: nums for path, nums in owners.items() if len(nums) > 1}
    lines = [_CONFLICT_HEADING, ""]
    if not conflicts:
        lines.append("无跨组文件冲突。")
        return "\n".join(lines)
    lines.extend(["| 文件 | 涉及组 |", "|----|----|"])
    for path, nums in sorted(conflicts.items()):
        lines.append(f"| {path} | {', '.join(sorted(nums))} |")
    return "\n".join(lines)


def _render_file_tree(*, groups: list[Group]) -> str:
    """块 4：设计文件结构——所有组所有 Task 的 files 并集铺成目录树，每个文件标注归属 Task。

    数据全部派生自各 Task 的 `files` 声明（单一真相源），随 spec 演化自动更新，无需手工维护；
    一个文件被多个 Task 占用时并列标注其归属（与「文件冲突报告」呼应）。
    """
    # path -> 占用它的限定 Task id 集合（如 0001/T1）。
    owners: dict[str, set[str]] = {}
    for group in groups:
        for task in group.tasks:
            qid = model.qualified_id(group=group.number, task_id=task.id)
            for path in task.files:
                owners.setdefault(path, set()).add(qid)

    lines = [_TREE_HEADING, ""]
    if not owners:
        lines.append("（暂无 Task 声明文件）")
        return "\n".join(lines)
    lines.append(
        "> 下列结构由各 Task 的 `files` 声明并集自动汇总；`←` 后为归属 Task（多占即冲突）。"
    )
    lines.append("")

    # 1. 构建嵌套树：目录段为 dict，文件叶子为 None。
    tree: dict = {}
    for path in owners:
        node = tree
        parts = path.split("/")
        for index, part in enumerate(parts):
            if index == len(parts) - 1:
                node.setdefault(part, None)  # 文件叶子（已是目录则保留目录）
            else:
                child = node.get(part)
                if not isinstance(child, dict):
                    child = {}
                    node[part] = child
                node = child

    # 2. DFS 收集有序行（目录在前、文件在后，各自字典序），记录深度与归属。
    entries: list[tuple[int, str, str | None]] = []  # (depth, name, owner|None)

    def _walk(*, node: dict, depth: int, prefix: str) -> None:
        dirs = sorted(k for k, v in node.items() if isinstance(v, dict))
        files = sorted(k for k, v in node.items() if not isinstance(v, dict))
        for name in dirs:
            entries.append((depth, name + "/", None))
            _walk(node=node[name], depth=depth + 1, prefix=prefix + name + "/")
        for name in files:
            owner = ", ".join(sorted(owners.get(prefix + name, set())))
            entries.append((depth, name, owner))

    _walk(node=tree, depth=0, prefix="")

    # 3. 归属列对齐：以最宽的「缩进 + 文件名」为基准右侧补空格，箭头列对齐。
    indent = "  "
    widths = [len(indent * d) + len(name) for d, name, owner in entries if owner is not None]
    col = max(widths) if widths else 0
    lines.append("```text")
    for depth, name, owner in entries:
        left = indent * depth + name
        if owner is None:
            lines.append(left)
        else:
            lines.append(f"{left}{' ' * (col - len(left))}  ← {owner}")
    lines.append("```")
    return "\n".join(lines)


def _render_features(*, groups: list[Group]) -> str:
    """块 4：每 feature 段——组内看板 + 依赖 DAG + 演化图。"""
    lines = [_FEATURE_HEADING]
    for group in groups:
        title = group.metadata.title or group.metadata.slug
        lines.append("")
        lines.append(f"### {group.number} {title}（issue #{group.metadata.issue}）")
        lines.append("")
        lines.append(
            f"> 人读方案见 [`{group.number}-{group.metadata.slug}/summary.md`]"
            f"(./{group.number}-{group.metadata.slug}/summary.md)。"
        )
        # 组级导语也进 OVERVIEW：把各 feature 段从「只有链接 + DAG」升级为带叙事，
        # 让看板页本身能把三组串成一条故事线，而非纯节点图索引。
        if group.metadata.overview.strip():
            lines.append("")
            lines.append(group.metadata.overview.strip())
        # 任务一览：每个当前版 Task 一行（标题 + 状态 + 一句话摘要），让只看 OVERVIEW 的读者
        # 不点进 summary.md 也能掌握每个任务在做什么（修复「总览太薄」）。
        if group.tasks:
            lines.append("")
            lines.append("**任务一览**")
            lines.append("")
            for task in group.tasks:
                gist = _one_line(text=task.summary)
                tail = f" — {gist}" if gist else ""
                lines.append(f"- **{task.id} {_cell(task.title)}**（{task.status}）{tail}")
        lines.append("")
        lines.append(_render_group_dag(group=group))
        # 演化图只在「确有版本演化」时才画：否则每个节点都是 Tx v1、全 pending、零血缘，
        # 是一段对人零信息的噪音。等出现历史版本或血缘（split/merge/supersede/derive）时自动出现。
        if _has_evolution(group=group):
            lines.append("")
            lines.append(_render_evolution(group=group))
    return "\n".join(lines)


def _has_evolution(*, group: Group) -> bool:
    """组内是否存在真实演化：有历史版本，或当前版 Task 带任一血缘字段。"""
    if any(group.history.values()):
        return True
    return any(
        task.split_from or task.merged_from or task.supersedes or task.derived_from
        for task in group.tasks
    )


def _render_group_dag(*, group: Group) -> str:
    """组内依赖 DAG（Mermaid）；无任务时给占位。"""
    lines = ["```mermaid", "graph LR"]
    ids = {task.id for task in group.tasks}
    for task in group.tasks:
        lines.append(f'    {_node(task.id)}["{task.id} {_cell(task.title)}"]')
    for task in group.tasks:
        for ref in task.depends_on:
            # 组内 DAG 只画组内依赖（跨组在全局关系图体现）。
            if "/" not in ref and ref in ids:
                lines.append(f"    {_node(ref)} --> {_node(task.id)}")
    if not group.tasks:
        lines.append("    empty[空]")
    lines.append("```")
    return "\n".join(lines)


def _render_evolution(*, group: Group) -> str:
    """组内演化图：节点=某 Task 某一版，按 status 着色，血缘字段连边。"""
    lines = ["演化图：", "", "```mermaid", "graph LR"]

    # 1. 汇总每个 task 的版本序列（历史版 + 当前版），current 节点便于血缘连边。
    versions = _task_versions(group=group)
    used_status: set[str] = set()
    node_class: list[str] = []

    # 2. 节点声明 + 同 task 版本间 redefined 链。
    for task_id in sorted(versions):
        chain = versions[task_id]
        for snapshot in chain:
            node_id = _ver_node(task_id=task_id, version=snapshot.version)
            lines.append(f'    {node_id}["{task_id} v{snapshot.version}"]')
            used_status.add(snapshot.status)
            node_class.append(f"    class {node_id} st_{_safe(snapshot.status)};")
        for older, newer in zip(chain, chain[1:], strict=False):
            lines.append(
                f"    {_ver_node(task_id=task_id, version=older.version)} "
                f"-->|redefined| {_ver_node(task_id=task_id, version=newer.version)}"
            )

    # 3. 血缘边（split / merged / supersedes / derived）：源 task 最新版 → 本 task 首版。
    lines.extend(_lineage_edges(versions=versions))

    # 4. 着色 classDef（仅声明用到的 status，保证确定性）。
    for status in sorted(used_status):
        fill = _STATUS_FILL.get(status, "#ffffff")
        lines.append(f"    classDef st_{_safe(status)} fill:{fill};")
    lines.extend(node_class)
    lines.append("```")
    return "\n".join(lines)


def _task_versions(*, group: Group) -> dict[str, list[Task]]:
    """每个 task_id → 版本序列（历史版按版本号 + 当前版），用于演化图。"""
    all_ids = set(group.history) | {task.id for task in group.tasks}
    current = {task.id: task for task in group.tasks}
    result: dict[str, list[Task]] = {}
    for task_id in all_ids:
        chain = sorted(group.history.get(task_id, []), key=lambda t: t.version)
        if task_id in current:
            chain = [*chain, current[task_id]]
        result[task_id] = chain
    return result


def _lineage_edges(*, versions: dict[str, list[Task]]) -> list[str]:
    """从最新版 Task 的血缘字段连边：源最新版 → 本 task 首版。"""
    edges: list[str] = []
    for task_id in sorted(versions):
        chain = versions[task_id]
        if not chain:
            continue
        latest = chain[-1]
        first_node = _ver_node(task_id=task_id, version=chain[0].version)
        specs = [
            ("split", [latest.split_from] if latest.split_from else []),
            ("merged", latest.merged_from),
            ("supersedes", latest.supersedes),
            ("derived", latest.derived_from),
        ]
        for label, refs in specs:
            for ref in refs:
                src_id = ref.split("/")[-1]  # 演化图限组内，取末段 task id
                if src_id in versions and versions[src_id]:
                    src_node = _ver_node(task_id=src_id, version=versions[src_id][-1].version)
                    edges.append(f"    {src_node} -->|{label}| {first_node}")
    return edges


def _resolve(*, ref: str, group: str) -> str:
    """组内简写 → 限定 ID。"""
    return ref if "/" in ref else model.qualified_id(group=group, task_id=ref)


def _node(qid: str) -> str:
    """限定 ID → 合法 Mermaid 节点名（n + 非字母数字转下划线）。"""
    return "n" + _safe(qid)


def _ver_node(*, task_id: str, version: int) -> str:
    """演化图版本节点名。"""
    return f"v_{_safe(task_id)}_{version}"


def _safe(text: str) -> str:
    """把任意串转成 Mermaid 安全标识（非字母数字 → 下划线）。"""
    return "".join(ch if ch.isalnum() else "_" for ch in text)


def _cell(text: str) -> str:
    """表格 / 节点 label 单元：压成单行、转义竖线。"""
    return text.replace("\n", " ").replace("|", "\\|").replace('"', "'")


def _one_line(*, text: str) -> str:
    """取 prose 首句（到第一个句号止），压成单行——用于 OVERVIEW 任务一览的一句话摘要。

    先把换行/多空白压成单空格，再截到第一个「。」（含），避免一览里出现断句的半行。
    """
    flat = " ".join(text.split())
    if not flat:
        return ""
    head, sep, _rest = flat.partition("。")
    return _cell(head + sep)

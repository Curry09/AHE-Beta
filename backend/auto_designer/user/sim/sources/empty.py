"""empty SeedSource（spec-0009/T2）。

新建一个隔离空工作区目录；`params.doc` 非空时把其文本写成 `params.doc_name`（缺省
"SPEC.md"）的说明文件，覆盖 NL2Repo 式「仅一份需求文档、空仓起步」的注入形态。

可插拔证明：接入它只新增本模块——靠 spec-0009/T1 的 sources/ 自动发现注册，seed_source /
models / workspace 与消费侧（sim_user / Sandbox）一律不改。不引入容器 / git / 依赖供给。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from auto_designer.models import WorkspaceSpec
from auto_designer.user.sim.seed_source import register


@register("empty")
class EmptySource:
    kind = "empty"

    def provision(self, spec: WorkspaceSpec, dest_root: str | None = None) -> str:
        if dest_root is None:
            dest = Path(tempfile.mkdtemp(prefix="sim_ws_empty_"))
        else:
            dest = Path(dest_root) / "empty"
            dest.mkdir(parents=True, exist_ok=True)
        doc = spec.params.get("doc")
        if doc:
            name = spec.params.get("doc_name", "SPEC.md")
            (dest / name).write_text(doc)
        return str(dest.resolve())

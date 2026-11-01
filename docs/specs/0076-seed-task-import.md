---
number: "0076"
title: 旧 seed 卡库与纯文本任务导入
issue: 0
slug: seed-task-import
summary: 把明确提供的 seed 卡或文本指令转换成既有 ordinary task package，经同一冻结与 local/E2B 生命周期执行，不恢复旧入口或携带隐藏评估字段。
tasks:
  - id: T1
    title: 旧卡与文本材料转换
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/experiment/task_import.py
      - backend/tests/test_experiment_task_import.py
    scope: 严格转换输入，阶段式无覆盖发布既有任务包与来源摘要
    acceptance: 真实七卡可导入；Git pin与setup语义正确；隐藏字段不输出；错误与覆盖不产生成功产物
  - id: T2
    title: 统一任务CLI与公开命令检查
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/experiment/cli.py
      - backend/tests/test_experiment_cli_v2.py
      - backend/scripts/check_experiment_repository.py
      - backend/tests/test_experiment_repository.py
    scope: task import-seeds/from-text接线与准确公开命令白名单
    acceptance: help/参数/退出码/JSON有效；转换不读取凭证或进入生命周期
  - id: T3
    title: 双语输入教程与当前示例
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - docs/tutorials/seed-task-import.md
      - docs/tutorials/seed-task-import.zh-CN.md
      - docs/CONFIGURATION.md
      - docs/CONFIGURATION.zh-CN.md
      - README.md
      - README.zh-CN.md
      - examples/seed-inputs/library.json
      - examples/seed-inputs/instruction.md
      - CLAUDE.md
    scope: 解释转换和数组路径接入，提供当前小示例，更新历史能力迁入状态
    acceptance: 英中命令一致；不宣称隐藏sidecar或旧环境已复现；当前示例可转换和检查
  - id: T4
    title: 转换到冻结与真实工作区验收
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
      - T3
    relates-to: []
    parallel: false
    files:
      - backend/tests/test_experiment_task_import_e2e.py
      - backend/scripts/e2e-spec-0076-seed-task-import.sh
      - .github/workflows/experiment-contract.yml
    scope: 验证真实材料冻结与无副作用转换，真实Docker准备及模型local运行和工作区导出
    acceptance: 实际产物进入既有哈希合同；全仓回归；真实local模型实验完成收集清理，云端与演化边界明确
---

# 0076 · 旧 seed 卡库与纯文本任务导入

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

给统一入口增加 `task import-seeds LIBRARY --output DIR [--seed ID ...]` 和 `task from-text --instruction PATH --id ID --output DIR --not-in-benchmark`。两者只准备材料，不启动实验：生成当前 v1 ordinary task package、说明、setup、requirements 文件与路径索引，再交给现有 workload.task_packages、check/prepare/run 和 local/E2B 生命周期。旧卡的文本任务使用初始 scratch 源目录，不恢复旧脚本或新增 controller。

## Motivation

旧流程能直接读取 seed 卡库，卡的 task.prompt 作为真实需求；没有仓库时使用空 scratch 工作区。统一入口目前要求完整任务包，用户只能手工补 source/setup，旧输入流程因此没有迁入。直接恢复旧 seed runner 会重复冻结、认证与资源治理。本功能在材料边界转换，保留同一运行合同；导入成功不证明旧环境完全复现或任务通过。

## Guide-level explanation

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py --json task import-seeds research/archives/legacy-materials/seeds.json --output /absolute/path/to/imported-tasks
uv run --locked --extra experiments python backend/scripts/experiment.py --json task from-text --instruction examples/seed-inputs/instruction.md --id text-example --output /absolute/path/to/text-task --not-in-benchmark
```

卡库支持裸数组或含 seeds 数组的对象；逐卡按输入顺序导入，显式 --seed 可重复但不能重复指定同一 ID。选中卡必须有效。输入文件缺失、空库、重复 ID、无非 benchmark 声明、缺 prompt、错误 Git revision 或 setup 类型会拒绝，不产生可用的半批材料。输出目录必须不存在（包括空目录或符号链接），不覆盖已有产物。命令不读取模型/provider 凭证，不调用网络、不运行 setup。

返回结果提供绝对 task_packages 数组，可直接写入实验 JSON 的 workload.task_packages。输出 tasks.json 保存以输出目录为基准的相对路径、顺序与输入摘要，它不是新的实验定义或可以替代数组的入口；路径移入别处时应按实验 JSON 的目录调整。persona、轮次与模型仍由实验定义配置。

## Reference-level explanation

### 材料转换合同

新增 experiment/task_import.py，两个公共函数 import_seed_tasks 与 import_text_task。选中卡必须是对象，id 满足已有任务包 ID 规则且库内唯一；source.not_in_benchmark 必须为 true，task.prompt 必须为非空字符串。复用 distill.seed_library.validate_card 的字段/词表约束，但补齐其未强制的必需字段，不沿用 SeedLibrary 缺文件即空库的回退。原始 prompt 字节文本进入 instruction.md，不追加 task.context。拒绝卡、benchmark 卡、SeedScenario 适配后信封不能混进真实 seed 输入。

无 source.repo 或 n/a 时生成 scratch source/README.md，说明这是待实现任务的初始目录，不增加题目解答。现有冻结器拒绝空源目录，因此用说明文件建立可哈希的初始材料；旧文本任务同样最终在 scratch 中运行，用户/工具仍通过当前隔离工作区访问。带 repo 的卡要求无凭证 HTTPS 和 owner/repo 标识，env.repo_at 必须为固定 40 位小写 SHA；现有 load_task_package 验证生成结果。task.source 继续只有 local/git，kind=ordinary 与 not_in_benchmark=true。

setup 使用现行 TASK_ROOT/TASK_PYTHON/VIRTUAL_ENV/UV_BIN 合同创建任务 venv，环境固定后逐条以独立 bash 子进程执行原 env.setup 字符串，保持引号、换行和列表顺序；不对文本做 split/join，不实际执行命令。生成 requirements.lock 明确旧 setup 未自动锁定依赖，无 setup 的文本任务没有外部依赖。base_image、external_deps、预算或配对元数据没有对应自动迁移，不能把转换说成原环境已通过复现门。

### 隐藏字段与发布

只输出允许映射的 prompt/source/setup。oracle、env.test_cmd、gates、provenance 不复制到任务或任何 sidecar，不从其内容生成说明/依赖/反馈。tasks.json 的输入来源只保留字节摘要、ID、源类型，不保存原卡内容；金标准和隐藏测试不进入冻结材料。纯文本导入需显式 --not-in-benchmark，不能凭文本内容自动推断来源。

先在同父目录的临时 staging 写完并通过现有包校验，再以独占 mkdir 创建目标、移动生成文件；已存在任意目标拒绝。失败只清理本次创建的目录和 staging，不删除原输入或其他输出。不承诺跨平台强原子目录可见性，成功返回时材料完整，失败没有可误用的成功索引；不采用可能覆盖已有空目录的裸 rename。

### Task DAG 与文件分配

T1 转换核心、T2 CLI 和 T3 双语文档按本文件的稳定接口独立实施；T4 综合验收依赖三者。frontmatter 是唯一文件所有权表，组最多四项。CLI 新 task 命令同步公开命令白名单；不扩张 task schema 或复制历史入口。专项脚本 backend/scripts/e2e-spec-0076-seed-task-import.sh 覆盖真实七卡转换、混合 Git/文本、UTF-8/引号、无网络/模型/setup 执行、禁止字段哨兵、覆盖拒绝、选项与冻结生产集成。真实 Docker scratch setup/文件修改/预测导出单列验收；E2B 未实测时明确记录，不用离线替身冒充。

## Drawbacks

旧卡不会一键生成完整实验：persona/模型/轮数仍需用户配置。旧 setup 可包含未锁定依赖；转换不会替用户确定版本或下载代码验证。scratch 中有初始 README，比历史裸空目录多一个说明文件，但不会包含任务答案。生成任务需另存目录，占用少量空间；发布首版不承诺强原子目录可见性。

## Rationale and alternatives

恢复 --seed-library 的旧 runner 会重复运行路径且绕过统一材料合同，拒绝。把新 source.kind=none 或 legacy.seed DSL 贯穿双后端与编排层，需要更大分叉，却只解决缺少初始代码；不选。转换为现有任务包能复用已验证的单/多任务、批次、隔离与恢复，让来源适配和执行各自保持单一职责。

## Prior art

旧 distill.seed_adapter 将 task.prompt 映射为说明，有 repo 时生成 Git 工作区，缺 repo 时 workspace=None；但它未严格限制 SHA 且会改写 setup 引号，不能直接当新导入器。现行 ordinary task package 具有固定源码、setup、指令及非 benchmark 声明；冻结 catalog/plan 将其绑定到每个会话。导入器只负责连接两者，不改变演化和反馈合同。

## Unresolved questions

本次授权范围没有待用户决定的实现问题。旧卡的镜像、外部服务和环境是否可复现由生成包的实际 check/prepare/run 验证；不在转换时自动猜测或联网。

## Future possibilities

可后续增补用户明确提供的依赖锁和迁移差异报告，或在统一实验编辑流程中引用任务包索引；不增加自动猜测模型、隐式寻找私人材料或任意宿主 env 透传。历史产物追加轮与工程 CI 的 runner 治理仍是另外的功能。

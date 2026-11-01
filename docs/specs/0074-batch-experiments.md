---
number: '0074'
title: 统一入口的批量实验管理
issue: 0
slug: batch-experiments
summary: 用显式配置列表冻结批次成员，按真实运行状态限流并复用单 run 的检查、启动、收集与停止恢复。
tasks:
- id: T1
  title: 批次输入与冻结成员账本
  status: done
  priority: P1
  tags: []
  depends-on: []
  relates-to: []
  parallel: false
  files:
  - backend/auto_designer/experiment/batch_config.py
  - backend/auto_designer/experiment/batch_store.py
  - backend/auto_designer/experiment/schemas/batch-v1.json
  - backend/tests/test_experiment_batch_config.py
  - backend/tests/test_experiment_batch_store.py
  scope: 严格校验批次列表并冻结配置身份，分离不可变intent/manifest与可变receipt，独立entry根与prepare中断恢复。
  acceptance: 
    无provider检查与恶意字段/路径/类型拒绝，原子发布和hash篡改拒绝，唯一子manifest恢复，不复制凭证或重建已有run。
- id: T2
  title: 复用单run的批次调度与恢复
  status: done
  priority: P1
  tags: []
  depends-on:
  - T1
  relates-to: []
  parallel: false
  files:
  - backend/auto_designer/experiment/batch.py
  - backend/tests/test_experiment_batch.py
  scope: 有限并发前台监督，持久launch 
    lease，先reconcile再dispatch，终态collect及stop/resume、UNKNOWN/LOST与失败阻塞。
  acceptance: 
    run返回不释放名额；UNKNOWN/collection失败保留lease；停止后接回相同run；崩溃启动意图不重复prepare/provision；失败阻止pending但继续观察已运行成员。
- id: T3
  title: 统一CLI批次子命令与仓库契约
  status: done
  priority: P1
  tags: []
  depends-on:
  - T1
  relates-to: []
  parallel: false
  files:
  - backend/auto_designer/experiment/cli.py
  - backend/tests/test_experiment_cli_v2.py
  - backend/scripts/check_experiment_repository.py
  - backend/tests/test_experiment_repository.py
  scope: 接线batch 
    check/prepare/run/status/stop/resume/collect，保持单run入口和参数语义，扩展公开仓库检查。
  acceptance: CLI JSON/退出码与凭证路径准确，旧命令不回归；仅一次公共入口；四个run示例与两个batch示例可检查。
- id: T4
  title: 批次示例与双语教程
  status: done
  priority: P1
  tags: []
  depends-on:
  - T1
  relates-to: []
  parallel: false
  files:
  - examples/batches/u1-u4-local.json
  - examples/batches/u1-u4-e2b.json
  - README.md
  - README.zh-CN.md
  - docs/QUICKSTART.md
  - docs/QUICKSTART.zh-CN.md
  - docs/CONFIGURATION.md
  - docs/CONFIGURATION.zh-CN.md
  - docs/tutorials/batch-experiment.md
  - docs/tutorials/batch-experiment.zh-CN.md
  - backend/tests/test_experiment_batch_examples.py
  scope: 维护两后端配置列表及一致的中文英文操作教程，说明费用/并发/仓限、前台监督和资源保留。
  acceptance: 材料引用真实有效，示例无私人路径/密钥，语言命令一致，明确N1/N4示例原本轮次不同及容量unknown不是证明配额足够。
- id: T5
  title: 批次闭环故障恢复验收
  status: done
  priority: P1
  tags: []
  depends-on:
  - T2
  - T3
  - T4
  relates-to: []
  parallel: false
  files:
  - backend/tests/test_experiment_batch_e2e.py
  - backend/scripts/e2e-spec-0074-batch-experiments.sh
  - docs/validation/batch-experiments.md
  scope: 运行真实批次store/scheduler与单run接线，在provider/model边界替身验收中断、非空交付、收集和恢复，记录真实覆盖。
  acceptance: 
    至少两run实际完成terminalcollect，UNKNOWN占槽、quota失败、崩溃恢复与重复调用不重复run/仓；离线替身与live证据明确区分。
---

# 0074 · 统一入口的批量实验管理

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

为统一 `experiment` CLI 增加一个批次层：用户显式列出若干现有 schema2 配置，先检查并冻结全部成员，再按有限并发启动；批次持久记录成员 run ID，持续核对单 run 的真实状态，终态收集后汇总。停止与恢复沿用原 run 的材料、仓库、checkpoint 和 backend，既不增加 controller，也不恢复历史 launcher。首版不提供参数矩阵、历史追加轮或官方评分。

## Motivation

当前单 run 已统一 local/E2B 的材料、凭证、控制器和生命周期，但执行 N1/N4/N8 对照还需要重复命令并人工维护 run ID。历史 scaling 脚本有选择集合、启动 gate 和 executor 封装，却绑定旧目录、模型 env 和旧云资源；其正式启动还限制每次一个 N。直接恢复该脚本会再次形成第二套入口。

更关键的是，`runtime.run_v2` 返回的是启动确认，不是实验完成。用线程池调用它并以函数返回释放并发名额，会把“最多同时运行两项”变成“每次同时启动两项、最后全部活跃”。批次必须持有运行租约并根据 provider/controller 的真实状态释放，同时在进程退出后能够重建相同调度决定。

## Guide-level explanation

用户准备 `examples/batches/u1-u4-local.json` 或对应 E2B 示例，首版公开格式如下：

```json
{
  "schema_version": 1,
  "name": "u1-u4-comparison",
  "max_parallel_runs": 1,
  "entries": [
    {"id": "u1", "config": "../experiments/u1-local.json"},
    {"id": "u4", "config": "../experiments/u4-local.json"}
  ]
}
```

路径相对批次文件解析；`id` 是安全且唯一的路径段。`schema_version`、`max_parallel_runs` 只接受正整数，不接受 bool。列表不能为空，拒绝未知字段。首版同批必须选择同一 backend；不同 backend 用不同 batch，避免一个 max_parallel 值掩盖不同 provider 配额。每个 entry 是完整现有配置，不允许局部覆盖、共享可写目录或任意 executor 命令。凭证只用现有 `--secrets-file`/显式注入环境，不写进批次 manifest、receipt 或日志。

```bash
uv run --locked --extra experiments python backend/scripts/experiment.py batch check --config examples/batches/u1-u4-local.json --offline
uv run --locked --extra experiments python backend/scripts/experiment.py batch prepare --config examples/batches/u1-u4-local.json --secrets-file .env.experiment
BATCH_ID=REPLACE_WITH_PRINTED_BATCH_ID
uv run --locked --extra experiments python backend/scripts/experiment.py batch run "$BATCH_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py batch status "$BATCH_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py batch stop "$BATCH_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py batch resume "$BATCH_ID"
uv run --locked --extra experiments python backend/scripts/experiment.py batch collect "$BATCH_ID"
```

`check --offline` 逐项调用真实离线材料检查，不加载凭证、不获取 Git、不造最终 digest；在线检查逐项复用普通 check，不额外调用模型。`prepare` 顺序冻结并准备全部成员，全部成功才让 batch 可启动。`run` 是前台批次监督循环，启动子实验后继续等待并汇报状态；不要把“成员 started”说成“整个 batch 完成”。Ctrl+C 停止批次监督和后续排队启动，已启动子 run 保留运行；它不会把 Ctrl+C 偷换成 cloud stop。要停止全部子 run 使用 `batch stop`。

`resume` 接回原批次成员：已有活动 run 只 attach；STOPPED 用现有 resume；未开始的 PREPARED 才 fresh run。失败或 LOST 不自动创建替代实验。`collect` 对已开始且可访问成员复用单 run collect，报告每项 COMPLETE/PARTIAL/error，不把部分收集误报全批完成。首版不提供自动 destroy 或删除仓库；用户依据 status 输出的单 run 命令显式清理。批次暂停不会释放 E2B 分配资源。

## Reference-level explanation

### 持久材料与所有权

批次目录为同一 runs root 下 `.batches/<batch_id>/`，不能与普通 run ID 混淆。目录拒绝 symlink、越界 ID 和 moved identity。包含不可变 `intent.json`（prepare 前保存已解析配置、成员顺序、统一 backend、输入摘要与创建时间）、全部成员冻结后一次原子发布的不可变 `manifest.json`（追加每项最终 config/material identity 的最终快照）、可变 `runtime.json`、追加 `journal.jsonl`，以及 `children/<entry_id>/<run_id>/` 独立单 run root。intent 与最终 manifest 各自只发布一次，不能把 prepare 期间变化的 material hash 反复写进所谓不可变 manifest。intent 已存在而最终 manifest 未发布时，run 明确拒绝，resume 只恢复 prepare 阶段。单 run manifest、resources、checkpoint 仍由原 runtime 写入；批次不改它们的冻结 identity。

批次 preparation 先写每项 prepare intent。一个 entry 使用专属 children root；当前 prepare API 没有预分配 run ID 接口，所以恢复时只在该 entry 的受控 root 中核对唯一完整 manifest，不对所有全局目录做时间猜测。完整 manifest 与预期 canonical config/material source 匹配后登记实际 run ID，再继续准备。0 个完整 manifest 且只有 `.preparing-*` 表示原子发布之前中断；应清楚报告未冻结并在明确 prepare retry 中重试。多个完整 manifest、身份不同或已存在不完整 prepared run 均 BLOCKED；首版不静默选一个、删除目录或重做材料。`prepare` 再次执行不能覆盖已冻结 batch，恢复 prepare 使用 `batch resume` 对 prepare-only 状态的分支；环境准备失败的既有子 run 在首版报告 BLOCKED_PREPARATION，指向单 run 日志与人工处理，不伪装支持不存在的原材料重建 API。

可变 receipt 至少保存 batch revision、批次暂停/监督状态、entry ID、唯一 run ID、child manifest/config/material摘要、launch intent/attempt、最近已观察三轴状态（experiment/resource/collection）、observation 和时间、active lease、collection receipt 引用、错误分类。错误信息应复用现有 credential redaction，不能转存原始带密钥异常。checkpoint、SessionStore 和单 run journal 始终是单 run 执行事实源，批次 receipt 是调度记录，不是另一个实验完成账本。

### 并发与调度

单 batch 使用进程级文件锁保证只有一个 scheduler；atomic write + revision/intent 保证崩溃可恢复。观察与单 run 操作使用现有 run locks。批次控制锁不能在整个云请求或整轮实验上长期占用，以便 status/stop 提交可见控制意图。状态更新采用短临界区；scheduler 在动作前后核对暂停意图。

一次占用名额从选择某个 PREPARED entry、持久写 launch intent 开始，覆盖 provisioning、preflight、启动、活动运行、STOPPING、无法确认的状态和终态 collect。普通排队的 PREPARED 不占名额。prepare 本身顺序执行且不启动资源，因此不会绕过活动上限。`run_v2` 返回、收到 exit code 或某条 progress 文本，均不是释放依据。

恢复 scheduler 时先观察所有有 launch intent 的成员并重建租约，再启动 pending；不能先使用旧 receipt 中的空闲数。`UNKNOWN`、`OPERATION_IN_PROGRESS`、无法判断启动是否产生资源的失败仍持名额；不因超时、网络错误或“最后见过 FAILED”释放。直到权威 observation 确认 controller 已停/退出，并完成终态收集，才释放运行名额。确认准备失败且没有任何 provision intent 的 entry 无 active lease，但会阻止整个 batch 开始。LOST 作为基础设施终态单独报告，不允许 fresh 替换；若 provider 明确证实资源消失可释放 active lease，未取得 COMPLETE 的终态收集仍保留失败原因及旧产物，batch 不可能成功。

终态 `COMPLETED` 必须来自单 run 封口判定。`FAILED`/`STOPPED` 也应尝试 collect，只有 COMPLETE 才完成该终态收集步骤；收集 PARTIAL/失败时 BLOCKED_COLLECTION 保留租约并停止后续启动，允许显式 `batch collect` 重试。为了首版保守，遇到一个成员 FAILED/LOST 后停止启动剩余 pending；已经运行的成员继续观察和收集，不自动 kill，也不自动重跑失败成员。batch 成功仅当所有成员实验 COMPLETED 且 collection COMPLETE；普通 STOPPED 是暂停，不是失败或成功。

`max_parallel_runs` 约束本 batch 活跃执行/不确定租约，不是总云资源数，也不是整个账号全局并发。独立运行、另一个 batch 和别人的资源不归此上限管理。公开 status 同时列 active/pending、已分配但停止/完成后仍保留的资源，以及配置的每 run 用户并发；不能把二者相乘描述成严格模型调用上限。

### 配额与操作

首版在线 preflight 在任何 start 前检查所有配置、凭证及可验证 provider 权限。已知 Gitea repository quota 不足就拒绝批次启动，提示本批次需要的新增仓库数；Gitea API 不保证公开剩余名额，无法证明时明确容量 UNKNOWN，不伪造 availability。实际建仓或 E2B capacity error 使用原失败分类、保留 intent/已创建资源、阻止后续 pending。每个新单 run 通常要独立仓库；destroy compute 不删除 Gitea 仓，因此顺序执行仍可能耗尽五仓上限。不得通过共享仓库、覆盖旧仓或自动删仓规避限制。

停止 batch 先持久 PAUSING、停止 dispatch，然后逐项调用现有 stop，仅对已经开始的 run 操作。STOPPING/UNKNOWN 不立即变 PAUSED；确认停止后保存 PAUSED。resume 校验 batch 与全部子材料摘要，不改变模型/任务/计划；如果凭证变化只接受现有 runtime 支持的认证输入，不跨账号接管旧仓。status 保留历史状态与最新 observation，遇 provider unknown 不推断 sealed/collected。collect 必须核对当前 generation/nonce 和已有 terminal receipt，避免旧快照冒充最新完成。

### Task DAG 与互斥文件所有权

| Task | depends-on | 独占 files | scope / acceptance |
| --- | --- | --- | --- |
| T1 批次输入、冻结身份与 receipt | 无 | `backend/auto_designer/experiment/batch_config.py`; `backend/auto_designer/experiment/schemas/batch-v1.json`; `backend/auto_designer/experiment/batch_store.py`; `backend/tests/test_experiment_batch_config.py`; `backend/tests/test_experiment_batch_store.py` | 严格公开字段、独立 entry root、无凭证 manifest、atomic revision/locking、篡改和越界拒绝、prepare intent恢复；不加载provider或运行模型。 |
| T2 生命周期 scheduler | T1 | `backend/auto_designer/experiment/batch.py`; `backend/tests/test_experiment_batch.py` | 只调用现有runtime API；真 active lease上限，启动返回不释放；中断前后不重复建仓/run；UNKNOWN/LOST/collection失败/stop-resume和quota分类。若接口审计证明必须扩展runtime，正式spec需将`runtime.py`及其相应test一并归此Task，不能平行抢写。 |
| T3 统一 CLI 接线与仓库契约 | T1 | `backend/auto_designer/experiment/cli.py`; `backend/tests/test_experiment_cli_v2.py`; `backend/scripts/check_experiment_repository.py`; `backend/tests/test_experiment_repository.py` | batch子命令解析、--runs-dir/--secrets-file对齐、已有单run命令不变、JSON输出退出码、未collect/unknown不能宣称完成。 |
| T4 公开示例与双语文档 | T1 | `examples/batches/u1-u4-local.json`; `examples/batches/u1-u4-e2b.json`; `README.md`; `README.zh-CN.md`; `docs/QUICKSTART.md`; `docs/QUICKSTART.zh-CN.md`; `docs/CONFIGURATION.md`; `docs/CONFIGURATION.zh-CN.md`; `docs/tutorials/batch-experiment.md`; `docs/tutorials/batch-experiment.zh-CN.md`; `backend/tests/test_experiment_batch_examples.py` | 两backend同计划、真配置路径/credential refs、中英文命令一致；明确并发/费用/仓限/retain资源与 Ctrl+C/stop差异，无私人路径。 |
| T5 故障恢复闭环与验证报告 | T2、T3、T4 | `backend/tests/test_experiment_batch_e2e.py`; `backend/scripts/e2e-spec-0074-batch-experiments.sh`; `docs/validation/batch-experiments.md` | 真实batch store/scheduler接实际single-run runtime，provider/model边界替身；非空交付至少一项，两run完整terminalcollect；crash/restart、UNKNOWN占槽、quota、重复操作；真实local/E2B可用时再记录实际provider证据，不能将mock当live。 |

共五个 Task，DAG：T1→T2→T5，另有 T1→T3→T5、T1→T4→T5。T2 公共 Python 接口已固定，T3 可独立完成 CLI 接线；T5 必须同时等待调度、CLI 与文档完成。本组已通过 spec 工具建立正式组和所有权表，e2e 固定为 `backend/scripts/e2e-spec-0074-batch-experiments.sh`。

## Drawbacks

增加一层持久调度与控制状态，必须与单 run 三轴状态一致。UNKNOWN 保守占槽、collection失败阻塞会降低吞吐，但否则无法证明并发约束与终态证据。首版不自动销毁计算，用户必须处理保留资源与仓库配额；顺序批次也会增加总费用。准备全部成员可能先花构建时间，再发现某个成员冻结失败。批次不能让不可用的Docker、缺失云配额或失去的旧沙箱自动变可用。

## Rationale and alternatives

选择显式配置列表、同backend批次、默认并发1，是因为当前schema2已经描述全部模型/角色/任务/用户材料，薄包装不应再定义实验核心。scheduler调用Python runtime，避免shell子进程复制认证、把输出文字当状态或遗漏providerintent。

备选一是文档给shell for循环：实现容易，但缺持久成员映射、停止恢复、真实active上限与collectiongate。备选二是直接复活历史scaling runner：有准备清单可借鉴，却绑定历史材料和旧executor，会再次形成双入口。备选三是加入参数矩阵、跨backend资源调度和自动quota扩容：需求面过大，不能与最小批次一组可靠完成。备选四是run返回即结束worker：不成立，因为当前run返回后实验仍在远端执行。

## Prior art

仓内活跃单run实现：`experiment/runtime.py` 的check/prepare/run/status/stop/collect/destroy，manifest run locks、atomic runtime/journal，以及既有monitor的terminalcollection。新组复用这些事实源，不重写backend或controller。

归档scaling runner提供历史plan、all-selectedgate和executor封装思路，但正式start/resume原本要求单N，且属于固定历史源码，不能直接import调用。维护的hbench有独立batchtrialledger，可参考对terminal/invalid的区分，不能混作演化experimentledger。官方评分、历史continuation仍另组；历史角色replay能重映射报告，却停止在OpenAgents之前，不等于batchresume。

## Unresolved questions

本组采用保守首版政策：同backend、默认并发1、遇失败停止pending、UNKNOWN占槽、终态collect后释放、无自动destroy、无自动重跑。用户已确认优先实施批量实验管理；上述边界作为本组确定的首版合同，若修改需同步状态转移和验收。批次准备中已冻结但环境prepare失败的修复API当前不存在，因此首版清晰阻塞而不许诺自动修复；若用户需要可靠自动重新构建环境，应作为正式组明确的小接口扩展纳入T2。

## Future possibilities

在批次身份与恢复验证稳定后，再提供配置矩阵编译、重复seed/重复trial、跨batch账号级资源池、显式after-collect销毁策略与预算停止。封存Harness SHA官方评分和历史产物continuation分别建立独立契约；它们可以成为批次成员的未来新类型，但不挤进当前只含schema2 experiment配置的首版。公开批次看板可随后复用已存在的run观察API，而不是本组新增并行前端。


# Integration validation / 集成验证

Recorded on 2026-10-09. These checks validate the integration, not leaderboard performance.
本记录验证接入链路，不代表正式 benchmark 成绩。

- Locked full repository regression: 2258 passed, 2 skipped. Subsequent evaluation
  regression, including the new recovery/upload cases: 120 passed, 2 skipped.
  The skips are optional τ² integrations whose framework was not installed.
- All 43 selected official task packages were downloaded and individually verified;
  their plan resolved resources, workdirs and budgets without starting benchmark Agents.
- E2B custom smoke used the frozen seed Harness with `glm-5.3-flash`: it created the
  required file, returned a terminal reply, and the verifier returned reward 1.
  E2B reported the declared 1 CPU and 2048 MiB allocation.
- Model-free live recovery interrupted the public CLI with SIGINT while its Harbor
  worker was active. Resume reconnected the same worker PID, completed grading,
  and retained an invocation-count artifact containing exactly one Harness launch.
- The integration wheel built and its stdio/task-pin modules imported in a clean
  Python environment without Harbor or sandbox packages.
- Ruff, format, whitespace and public-source boundary checks passed. Experiment
  directory validation still passed; the experiment launcher was unchanged.

Local Docker could not be tested because its Engine was unavailable. Daytona's
SDK/environment contract was checked, but no live Daytona run was performed.
The 43-task batch, official LLM judge access, every task family's verifier and
E2B's GAIA2 sidecar topology were not rerun in this integration validation.

本地 Docker 服务不可用；Daytona 本次只检查 SDK/环境接口，未做云端实测。
没有重跑整套 43 题，也没有据此宣称官方裁判、所有任务族和 E2B GAIA2 sidecar 均已验证。

## Directory consolidation validation (2026-10-09)

The current entry is `python -m evaluation`; the former schema-1 framework and
its optional Tau/user-simulator tests have been removed. The earlier validation
above records the preceding layout and remains historical evidence.

- Current evaluation suite: **51 passed**, including standard task packages,
  Index-only evidence/judge separation, nested source fingerprints, E2B Compose
  support selection and benchmark-supplied MCP instructions.
- Full repository initial regression: **2276 passed, 2 setup errors**. Both errors
  were the intended source-change guard while project/lock files were being
  edited during snapshot creation. The stable repository/grading regression then
  passed **88 tests**, covering both affected cases. No source guard was disabled.
- All **43 pinned Index tasks** passed download/file verification and planning.
  This does not claim completed scoring of those tasks.
- Live synthetic task smoke on **Docker, Daytona and E2B** used the frozen seed
  Harness with `glm-5.3-flash`. Each returned official verifier **reward 1**, one
  valid trial and no invalid attempts, with task-declared **1 CPU / 2048 MiB**.
  This validates the shared entry, not official benchmark performance.
- Model-free E2B SIGINT/resume validation retained the same worker PID and one
  Harness invocation; the verifier returned reward 1. The retained invocation
  artifact was counted by lines, not interpreted as an integer.
- The reorganized wheel/sdist built. Its entry, stdio and task hashing imported in
  a clean environment without Harbor installed, with no tests or bytecode in the
  wheel. The pinned Index release asset was included.
- A controller snapshot containing the root project and lockfile, without the
  held-out evaluation source, passed `uv sync --locked --extra experiments
  --extra dev --dry-run`. Evaluation no longer introduces an editable local
  package dependency into evolution snapshots.
- Ruff, formatting, whitespace and repository directory/provenance checks passed.

No full 43-task model batch, every family-specific verifier, or live GAIA2
sidecar evaluation was repeated. Existing runs must use their frozen checkout;
this directory change does not migrate their source fingerprints.

重组后的入口、三后端合成任务冒烟、任务材料校验和恢复链路已验证；没有据此宣称整套
官方任务评分通过。全仓首次运行的两项错误来自修改期间触发的源码快照保护，稳定文件后
已重跑通过，未关闭校验。旧版运行继续使用原冻结 checkout。

## Harbor 0.24.0 upgrade validation (2026-10-09)

The integration now pins Harbor 0.24.0, E2B 2.55.0 and Daytona 0.223.0.

- Locked full repository regression: **2290 passed**.
- Evaluation regression: **55 passed**, including native Compose service APIs,
  MCP/skills declarations, image/resource template identities, startup variables,
  cgroup allocation checks and verifier-only recovery with bundled or uploaded tests.
- All **43 pinned official Index task packages** passed integrity verification,
  native Task loading and contract resolution under the new Harbor version.
- Real public-entry synthetic trials on **Docker, Daytona and E2B** used a
  model-free stdio Harness. Each executed once and received verifier **reward 1**.
  Startup records confirmed **1 CPU / 2048 MiB** for the Agent and a separate
  **2 CPU / 4096 MiB** verifier. These trials test infrastructure and scoring,
  not model quality or an official benchmark score.
- E2B SIGINT/resume retained the same worker and one Harness invocation. A fresh
  E2B verifier-only run also returned reward 1 with unchanged artifact hashes
  and zero actor model requests.
- Native E2B creation and dynamic no-network policies blocked the tested HTTPS
  domain, HTTPS IP and HTTP IP endpoints with SDK 2.55.0. The old custom network
  override was removed; native policies and task startup variables are preserved.
- The first synthetic fixture incorrectly declared an Agent-only image as a
  bundled verifier image, so Harbor skipped test upload and reported missing
  rewards on all providers. The corrected fixture uses Harbor's inherited-image
  fallback and uploaded tests; no frozen task or result was edited in place.

E2B still needs image/resource-aware template cache keys and build locking.
Configurable sandbox lifetime and Index-specific ARE support remain separate
from native task budgets and network policies. The 600-second persistence grace
is unchanged. A full 43-task model batch and live ARE sidecar scoring were not
repeated for this upgrade.

本次升级验证了三后端真实合成任务、独立验收环境、实际资源、中断恢复与仅重跑验收，
没有调用模型，也不代表整套官方题目的成绩。首次自检的测试镜像声明错误已通过新的
独立运行修正；测试任务与结果未被覆盖。

## Python import isolation and MCP workspace validation (2026-10-09)

- Full repository regression: **2294 passed**; Ruff, format and whitespace checks passed.
- Evaluation regression: **59 passed**. Subprocess tests inject a foreign
  `json.py` and an invalid `PYTHONHOME`: the driver and frozen Harness child
  still start, while shell tools retain the task's original `PYTHONPATH`.
  GSO cleanup applies to an entire compound command and leaves unrelated
  task settings, Agent commands and other task families unchanged.
- Real E2B `gso-speedup-hf-datasets` setup now imports Pillow from the separate
  Harness Python 3.12 venv, while retaining the task's Python 3.9 import setting
  in the process environment. A model-free `/help` request returned successfully.
- Real E2B `gso-speedup-pandas-seq-to-range` verification startup ran the
  unchanged official `gso_evaluate.py --help` successfully. The scorer imported
  NumPy from `/opt/gso-venv/lib/python3.12/site-packages`; the project interpreter
  still imported its own Python 3.10 NumPy after activating the task venv.
- Real E2B `gaia2-adapt-hard-1` used the official ARE sidecar. The public client
  at `/app/.harbor-mcp/client.py` passed the unchanged archived Harness workspace
  boundary check, listed **114 public tools**, fetched the initial user message
  and collected the real event log and provenance. Scenario files were not
  copied into the public client's directory.
- The first ARE probe used a synthetic-smoke credential file without the
  required judge key and failed preflight. The probe was rerun with the existing
  evaluation credential file; credentials were not copied into public materials.

These are startup, Python import, MCP transport and artifact-collection checks,
not complete official task solves or new benchmark scores. No actor model
requests were made, original results were unchanged, and probe sandboxes were
deleted after use. The official task images, tests, scoring rules and archived
Harness source were preserved.

本次真实验证了 GSO 的 Harness／评分器导入隔离与项目环境保留，以及 GAIA2 的
工作区内公开客户端、官方工具调用和真实日志采集；没有重跑整套题目或改写原成绩。

## Native command cancellation validation (2026-10-10)

- Evaluation regression: **92 passed**; Ruff, formatting and whitespace checks passed.
- Two independent model-free E2B reproductions confirmed that cancelling the
  native command wait leaves remote work running, and killing only the SDK
  command PID can leave a pipeline child running.
- A separate E2B probe of the corrected installed-agent execution path confirmed
  that cancellation stopped and reaped an orphaned, detached writer: its pulse
  remained at 8 bytes across the subsequent observation. An unrelated command
  continued writing (23 to 37 bytes).
- Successful command exit preserved an intentional background service. Cancelling
  before a delayed remote command started prevented its later task work.
- The proof made **zero model calls** and deleted its sandbox. The dedicated
  stdlib runtime was checksum-verified; the task interpreter was not replaced.
- A public-entry synthetic E2B trial with Claude Code **2.1.119**, GLM-5.3 Flash
  and `reasoning_effort=max` created the required file, returned a normal terminal
  reply and received independent verifier **reward 1**. Harbor's native trajectory
  and usage backfill remained enabled; ownership receipts are separate log files.

These checks validate cancellation and normal-exit behavior, not benchmark scores.
Previous raw results remain unchanged. Host/guest timestamp differences alone
are not evidence that a particular previous score benefited from late execution.

本次验证原生命令取消、脱离进程组子进程的回收、独立命令不受影响、正常后台服务保留，
以及取消早于启动的竞态；没有据此宣称旧超时题目已通过或全部旧分数受影响。

## Runtime bookkeeping collection validation (2026-10-10)

- Evaluation regression: **97 passed**; Ruff, formatting and whitespace checks passed.
- Real Git tests confirmed that official `git add -A` retains task edits and new
  tests while omitting untracked runtime `.harness` records. Existing exclusion
  rules are retained, nested workspaces affect only their own path, and a
  task-owned tracked `.harness` path is not hidden. Non-Git tasks gain no repository.
- Two independent E2B probes used the pinned official SWTBench Agent image and
  its unchanged collection hooks. A synthetic task edit entered `/tmp/agent.patch`;
  the runtime record did not, and remained readable in the workspace.
- The second probe separately archived and downloaded the runtime records and
  read back their exact contents. Both probes made **zero model requests** and
  deleted their sandboxes.

These are collection and diagnostic-preservation checks, not official task solves.
Previously retained candidate patches remain unchanged; any derived submission
and subsequent verification must be recorded separately with their provenance.

本次验证运行日志与任务 patch 的边界，并确认日志另存后可读；没有修改官方测试或
候选任务代码，也没有据此宣称 SWTBench 候选通过。原 patch 与修正后的派生产物须分开保存。

## Command transport failure cleanup validation (2026-10-10)

- Evaluation regression: **103 passed**; Ruff, formatting and whitespace checks passed.
- A model-free local reproduction against the preceding implementation raised a
  host connection error after a real detached writer started. Its counter advanced
  from 0 to 15 after the exception, confirming that failure of the wait did not
  imply remote work had stopped.
- A separate E2B probe injected the same host wait error after actual remote work
  started. The native installed-agent execution path stopped and reaped its
  writer (72 to 72 bytes); the frozen Agent execution path did likewise (31 to 31).
  Unrelated remote work continued in both cases, and the original connection
  exception was preserved after cleanup. Cleanup receipts confirmed owner exit.
- The probe used synthetic stdlib-only drivers, made **zero model requests**, and
  deleted its sandbox. An earlier probe's attempt to download a host-only cleanup
  receipt failed; that diagnostic was retained and the corrected probe completed.
- A public-entry synthetic E2B trial using the frozen seed Harness and GLM-5.3
  Flash returned a normal reply in 10.53 seconds and received verifier **reward 1**.
  This checks that normal execution still works, not an official benchmark solve.
- Neither the official task solving budgets nor the 600-second persistence grace
  changed. Existing comparison workers remain on their frozen source; this repair
  and any subsequent retest have separate source identities and results.

本次验证宿主等待发生传输异常后先停止所属远端工作，再采集产物；原生与冻结 Harness
共用清理边界。保留原异常、清理收据和旧诊断，没有重发在途 Agent 请求或修改原始成绩。

## Archived watchdog outcome validation (2026-10-10)

- Evaluation regression: **114 passed**; Ruff, formatting and whitespace checks passed.
- Real stdio subprocess tests distinguish reserved timeout terminals, explicit
  timeout statuses and all-timeout typed LLM receipts from ordinary error replies,
  prose about historical timeouts and successful replies after a retry.
- Executor tests keep positive official rewards authoritative while recording an
  internal watchdog stop as `harness_self_timeout` and excluding it from normal replies.
- A model-free E2B replay used two retained terminal frames: a reserved `[timeout]`
  reply after two 300-second stalls, and an error reply with four typed 300-second
  LLM timeout receipts. Both passed through the actual frozen task-side driver and
  produced `normal_reply=false`, `termination_reason=HarnessSelfTimeout`.
- The replay used a synthetic entrypoint, made **zero model requests**, deleted its
  sandbox and verified that the original candidate artifacts remained unchanged.
  It validates metadata classification, not a new task solve or a model retry.
- Original outcomes and official rewards remain retained. Reclassification evidence
  is recorded separately; no task budget or archived watchdog setting is changed.

本次校正“内部看门狗提前停止”被当成普通失败或崩溃的标签；两次真实 driver 回放都未
调用模型，也没有把原始 0 分改成通过。归档 Harness 及官方任务预算均未调整。

## Watchdog stops with stale intermediate replies (2026-10-10)

- Evaluation regression: **124 passed**; Ruff and formatting checks passed.
- An archived window can return earlier assistant prose after its final model
  unit times out. Classification now checks agreeing in-round unit-close mirrors
  in the receipt and both attribution blocks, unique known unit identities, and
  a final LLM timeout. It rejects recovered retries, command timeouts, conflicting
  or missing mirrors, unknown/error closes and explicit different terminal statuses.
- A separate E2B replay passed the retained DNA-task terminal frame through the
  actual frozen driver: `normal_reply=false`, `HarnessSelfTimeout`. This used a
  synthetic entrypoint with **zero model requests**, preserved the original
  candidate artifacts and deleted the sandbox. The official zero is unchanged.

本次补齐“已做部分工作，最后一次模型调用超时，却返回旧中间文字”的分类；依据
归档 Harness 的结构化收口事实，不根据回复措辞猜测。没有重跑解题或改变任务成绩。

## Host driver diagnostics validation (2026-10-10)

- Evaluation regression: **129 passed**; Ruff and formatting checks passed.
- The frozen Agent saves the command's returned stdout/stderr on the host before
  remote bookkeeping collection. Known credential values are redacted. A host
  diagnostic write failure is recorded without replacing the execution outcome.
- Regression tests cover successful and nonzero exits, an independent remote
  collection failure, empty streams, credential redaction and a host write failure.
- A real E2B probe passed a synthetic protocol failure through the actual driver:
  the host retained its `HarnessProtocolError` traceback with the synthetic key
  redacted. A second normal reply preserved exit zero and both empty stream files.
  Both cases made **zero model requests**; the sandbox was deleted.
- The probe did not recreate a full filesystem or rerun an official task. Returned
  command streams cannot recover an earlier missing traceback, and an exception
  before the SDK returns a result still follows the existing transport cleanup path.

本次验证远端日志采集前在宿主保存 driver 输出；不修改任务评分。真实 E2B 探针验证了
协议异常的 traceback 与正常退出，未重现磁盘满，也不能补回旧运行缺失的日志。

## Verifier-only failure diagnostics (2026-10-10)

- Fresh artifact regrades now retain the failing phase, exception message and
  chained traceback, redacting known credential values. A cleanup failure is
  recorded separately before it propagates, preserving the earlier failure.
- Four injected-failure tests cover environment startup, artifact upload,
  verifier execution and cleanup. They check that immutable input bytes stay
  unchanged and neither a verifier nor an Agent is retried. The full evaluation
  regression is **144 passed**; Ruff and formatting checks passed.
- These are diagnostic tests, not a new official benchmark score or a recreated
  E2B outage. Missing diagnostics from prior attempts cannot be reconstructed;
  running attempts retain their frozen implementation. Time budgets, official
  tests, judge configuration and score validity rules are unchanged.

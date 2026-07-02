# 开发者侧改为「带 git 工具的 nexau agent」设计

- 日期：2026-06-27
- 状态：待确认 → 实现
- 缘起：现状用确定性 `DeveloperAgent`（subprocess 跑 git）+ run.py/release 的同步 bolt-on，与「纯 agent 驱动、harness 自进化」理念冲突。改为开发者 nexau agent 用 git CLI 自主完成改/提交/合并/发版/推送。

## 一、决策（本会话敲定）

1. **分工**：harness/用户侧 **只提 issue**（用户 agent 用 harness 产 issue → Gitea，现状不变）；**开发者 agent 做修改 + git 同步**。
2. **开发者 = 工具型 nexau agent**：用 `run_shell_command`（跑 git）+ 文件读写工具，在 harness 仓本地（LocalSandbox）自主：读 issue → 改 `agents/main.md` → `git add/commit` → 建 `fix/issue-N` → **merge 到 release** → 打 `vN` tag → `push` 到 Gitea。
3. **取消体感门禁作为发版闸门**：dev 直接发版；体感（test agent 跑会话）**退化成纯观测**（只进体感/issue 曲线，不挡发版）。哲学：纯 agent 系统，多迭代几轮即可，「直接发版→用→有 bug 下轮修」，类比梯度下降，不做灰度。
4. **撤掉确定性胶水**：run.py `_wire_gitea_origin`、release.py `_push_origin`、以及 `DeveloperAgent` 里确定性的 `_run_git/_push/_commit/_route` 与 `release()` 的 merge/tag 逻辑（改由 dev agent 用 git 工具做）。Gitea origin 设置归到「种 harness 仓」时一次性配好（仓初始化的一部分，非编排层 bolt-on）。

## 二、新闭环

```
a  用户 agent 用 harness（release 版）→ 体感 + issue（→ Gitea）        【不变】
b  开发者 nexau agent（git 工具）：领一条 open issue → 改 agents/main.md
     → git commit/branch fix/issue-N → merge 到 release → tag vN → push Gitea   【全 agent 自主】
   多 dev：依次各领不同 issue（串行，后者基于前者已发版 release）           【不变】
c  新 release（最新 tag）回灌下一轮                                       【不变】
观测  test agent 跑体感会话 + metrics 画曲线，benchmark held-out          【不再挡发版】
```

## 三、组件改动

### 新增：`agent_defs/developer_agent/`（工具型 nexau agent 定义）
- `agent.yaml`：`tool_call_mode: structured`、`max_iterations`（如 60）、`llm_config`（model/base_url/api_key/max_tokens 32768/timeout）、`sandbox: local`、`tools:` 含 `run_shell_command` + `read_file` + 文件编辑工具（apply_patch/replace）+ `list_directory`/`search_file_content`。
- `systemprompt.md`：开发者角色指令 —— 给定 issue（号/标题/正文）与 harness 仓（cwd，已配 origin=Gitea），完成「改 main.md → 建分支 → merge release → tag → push」，最后用结构化输出报告 `{branch, tag, pushed}`。
- `tools/*.tool.yaml`：从 nexau `code_agent` 示例 / `nexau.archs.tool.builtin` 复制所需工具定义。

### 改：开发者驱动（替换 `DeveloperAgent`）
- 新 `AgenticDeveloper`：构造工具型 dev agent（指定 cwd=harness 仓 + 注入 Gitea 凭证/NO_PROXY 到 sandbox 环境），`work_one(skip)`：从 tracker 取一条未认领 open issue，把 issue 拼进 prompt 跑 agent，解析其结构化输出得 `{issue_number, branch, tag, changed}`（供编排回灌 ref + 关 issue）。
- nexau agent 失败/超时沿用线程级硬超时兜底。

### 改：`Orchestrator.run_round`（b 段）
- 不再 `evaluate→release` 闸门；改为：每个 dev `work_one(skip)` 自己改+发版，返回最新 `tag` → 链式回灌 `ref`。test agent 仅作观测（可选：仍跑体感会话进曲线，但不参与控制流）。

### 改：`run.py`
- 删 `_wire_gitea_origin` 调用（origin 设置移进 `_seed_harness_repo`：种仓时加 origin + 初始 push）。
- dev 用 `AgenticDeveloper`（注入 Gitea 凭证）。
- 体感门禁 tester 退化为观测（或保留跑会话只为曲线）。

### 改：`release.py` / `developer_agent.py`
- merge/tag/push 改由 dev agent 做 → `release()` 与 `DeveloperAgent` 确定性 git 逻辑大幅删减或移除。保留 tracker 关 issue（可由编排在拿到 dev 结果后做，或 dev agent 报告后编排做）。

### 测试
- dev agent 的工具执行依赖真 nexau + git，难纯单测；以**最小本地 git 仓 + 假 issue 跑一次 agent**做集成 smoke（需真模型，慢）。单测层保留：编排在「dev 返回 tag」下的 ref 回灌、issue 去重 skip、metrics 观测。

## 四、风险与权衡
- **可靠性下降**：LLM 跑 git 不如确定性稳（可能跑错命令、合并冲突处理不当）。缓解：prompt 给明确 git 步骤 + 失败下轮重修（梯度下降容忍）。
- **安全**：LLM 在 LocalSandbox 跑 shell，限定 cwd=harness 仓；Gitea 凭证仅注入该 sandbox 环境。
- **无门禁**：harness 可能短期退化；靠 issue 曲线观测 + 多轮迭代回正（设计已接受）。

## 五、不在本次
- 真·并行独立多 dev（仍串行链式）。
- harness 自身带工具（harness 仍纯聊天，只提 issue 经用户 agent）。

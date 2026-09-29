---
number: "0027"
title: 统一 agent 结构化产出契约：issue_schema 单一真源 + submit-tool 原生校验，去掉第二次 LLM 重排与各自为政的解析
issue: 0
slug: unified-agent-output-contract
summary: 现状三个产结构化输出的 agent（用户 sim / triage / synthesizer）用了三套完全不同的严格度，且都是补丁摞补丁——issue_schema 的 USER 段是死代码（用户 sim 走自由文本、prompt 无约束、render/validate(section=user) 生产零调用）；triage 靠「第二次 LLM 调用做 json_schema 重排 + 括号扫描 + 一堆别名归一」三层兜底；synthesizer 只用括号扫描 + 容错映射、不用约束解码。本 spec 统一为：issue_schema 收敛成规范化字段的单一真源（去 USER/TRIAGE 分段，用户 body 保持自由文本 = 真实用户），并生成 submit-tool 的 input_schema；triage / synthesizer 各用一个带 input_schema 的 submit 工具原生吐结构化——nexau 在工具调用层用 jsonschema 强校验（违规抛 ToolValidationError→agent 重试），driver 直接读已校验参数。删掉第二次 LLM 重排、括号扫描、per-agent 别名归一，改为一处共享的「读 submit 参数 + 统一降级」。纯重构编排/agent 产出路径，不改闭环 a→d1→d2→b 语义、不引 benchmark。
tasks:
  - id: T1
    title: issue_schema 收敛为契约单一真源 + 契约生成/共享校验模块
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/auto_designer/demand/issue_schema.py
      - backend/auto_designer/demand/agent_contract.py
      - backend/tests/demand/test_issue_schema.py
      - backend/tests/demand/test_agent_contract.py
    scope: issue_schema 去 USER/TRIAGE 分段——用户 body 保持自由文本（真实用户不填模板），schema 只声明「规范化产物」字段（triage 的 根因区域/边界/验收 等按 kind、RFC 的 问题/根因/…）；删死掉的 USER 段与只在测试出现的 section=user 路径。新增 agent_contract 模块：由 SCHEMAS 单一真源生成各 producer 的 submit tool input_schema（triage dispositions / RFC proposals），并提供一处共享的「读 submit 参数 → 校验 → 统一降级(needs_info/skip)」helper，供 T2/T3 复用。validate/render 保留用于 body 渲染与 driver 二次把关。
    acceptance: issue_schema 无 USER 段死代码；agent_contract 能由 SCHEMAS 生成 triage/RFC 的 input_schema 且与 SCHEMAS 同源（改字段只改 SCHEMAS）；共享降级 helper 有单测；test_issue_schema/test_agent_contract 绿。
  - id: T2
    title: triage 改 submit-tool 原生结构化（去第二次 LLM 重排与别名归一）
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: true
    files:
      - backend/auto_designer/demand/triage.py
      - backend/agent_defs/triage_agent/tools/submit_triage.tool.yaml
      - backend/agent_defs/triage_agent/agent.yaml
      - backend/agent_defs/triage_agent/systemprompt.md
      - backend/tests/demand/test_triage.py
    scope: 给 triage agent 一个 submit_triage 工具，input_schema 由 T1 的 agent_contract 生成（issue/disposition/kind/priority/fields，enum 锁四值与 P0-P3）；设为 stop tool，agent 直接以工具参数吐 dispositions，nexau jsonschema 强校验、违规 ToolValidationError→重试。driver 从工具参数读已校验结果、走 T1 共享降级路径落库。删 _normalize_dispositions（第二次 LLM 调用）、_parse_dispositions/_disposition_of/_issue_num/_accept_fields 别名归一；systemprompt 去手抄 JSON 契约、改为「调 submit_triage 提交」。保留最小兜底（agent 未调 submit 则本轮 no-op、记日志）。
    acceptance: triage 一轮仅 1 次 LLM 调用；dispositions 经 nexau 校验（漂移字段/非法 enum 吐不出）；driver 读工具参数落库；采纳/重复/驳回/needs_info 四路仍正确、缺字段仍降级 needs_info；test_triage 重写为 submit-tool 路径且绿。
  - id: T3
    title: synthesizer 改 submit-tool 原生结构化 + 统一 driver-apply
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: true
    files:
      - backend/auto_designer/demand/synthesizer.py
      - backend/agent_defs/synthesizer/tools/submit_rfcs.tool.yaml
      - backend/agent_defs/synthesizer/agent.yaml
      - backend/agent_defs/synthesizer/systemprompt.md
      - backend/tests/loop/test_synthesizer.py
    scope: 给 synthesizer(synthesize) agent 一个 submit_rfcs 工具，input_schema 由 T1 agent_contract 生成（title/fields[RFC 字段]/covers）；设为 stop tool，agent 直接吐 proposals，nexau 强校验。driver 从工具参数读已校验结果、走 T1 共享路径落库 RFC + supersede covers。删 _parse_proposals 括号扫描、_rfc_fields_by_label/_norm_label 的解析用途（若 triage 也不再用则一并清）、_unwrap_result 信封拆解（submit 后不再需要）；systemprompt 去手抄 fields 契约、改为「调 submit_rfcs 提交」。
    acceptance: synthesizer 产 RFC 走 submit-tool、经 nexau 校验；covers/supersede 行为不变；缺 fields 的提案被拒（工具层）或统一 skip；synthesizer 与 triage 共用同一 driver-apply/降级；test_synthesizer 重写且绿。
---

# 0027 · 统一 agent 结构化产出契约：issue_schema 单一真源 + submit-tool 原生校验

<!-- 本文件由 spec 工具维护：frontmatter 为结构化源数据（含 tasks DAG），正文为组级 rust-RFC 9 段总览。 -->

## Summary

把三个产结构化输出的 agent（用户 sim / triage / synthesizer）从「三套不同严格度、补丁摞补丁」统一到一条干净路径：**issue_schema 作规范化字段的单一真源 → 生成 submit 工具的 input_schema → agent 用带 schema 的 submit 工具原生吐结构化 → nexau 在工具调用层 jsonschema 强校验（违规重试）→ driver 直接读已校验参数、走一处共享的降级/落库**。删掉 triage 的第二次 LLM 重排、双方的括号扫描与 per-agent 别名归一；用户 body 承认就是自由文本（真实用户不填模板），去掉 issue_schema 的死代码 USER 段。纯重构产出路径，不动闭环语义、不引 benchmark。

## Motivation

走查当前实现（证据）：

1. **issue_schema 的 USER 段是死代码**：用户 sim 经 `report_issue(body)`（`user/sim/tools.py`）产自由文本，`sim_user._issue_draft_from_body` 直接把 body 塞进 issue + 打标签；`render/validate(section="user")` 在生产代码里**零调用**（只在 `test_issue_schema.py` 出现）。用户 prompt 里也没有对应字段约束。半个 schema 从未接线。
2. **约束手段三侧割裂**：triage 一轮 = **2 次 LLM 调用**（agent 干活 + `_normalize_dispositions` 用 `response_format=json_schema` 重排），失败再回退 `_parse_dispositions` 括号扫描 + `_disposition_of`/`_issue_num`/`_accept_fields` 别名归一；synthesizer 只有 `_parse_proposals` 括号扫描 + `_rfc_fields_by_label` 容错；用户侧啥也没有。
3. **不优雅的根**：缺一个统一的「agent 结构化产出」机制。schema 想当单一真源，但产出端各走各路、强制手段各不相同、USER/TRIAGE 分段建立在「用户会填模板」的错误假设上。约束解码更是「拿第二次 LLM 去修第一次」，既贵又仍可能漂。

关键事实：**nexau 在工具调用时就用 jsonschema 强校验参数**（`archs/tool/tool.py:738 jsonschema.validate(params, self.input_schema)`，违规抛 `ToolValidationError`）。这意味着「让 agent 用带 input_schema 的 submit 工具原生吐结构化」是现成能力——发出即校验、漂了重试，一次调用搞定，无需事后重排/解析。

## Guide-level explanation

统一后：

- **issue_schema** 只描述「规范化产物」的字段（按 kind），是契约的单一真源。用户报的 issue body 保持自由文本（persona 像真人一样写），不再假装有 USER 模板。
- **triage** 有个 `submit_triage` 工具：参数就是 dispositions 数组（每条 issue 一项，字段/枚举由 schema 生成的 input_schema 锁死）。agent 想结束就调它；nexau 校验参数，字段漂了/优先级非 P0-P3 直接被拒、agent 重试。driver 读到的永远是合规结构。
- **synthesizer** 同理有 `submit_rfcs`。
- **driver** 两侧共用一处「读 submit 参数 → 二次把关 → 统一降级（缺字段 needs_info / 非法 skip）→ 落库」。

对使用者：产出更稳（发出即校验）、更省（triage 从 2 次 LLM 调用降到 1 次）、更好懂（一套契约、一套落库）。

## Reference-level explanation

- **T1 · issue_schema + agent_contract**：SCHEMAS 去 section 维度，只留规范化字段；新增 `agent_contract.py`：`dispositions_input_schema()` / `rfc_input_schema()` 由 SCHEMAS 生成 nexau 工具 input_schema（enum 锁 disposition 四值、kind∈USER_KINDS、priority∈P0-P3、fields 键=各 kind 字段并集）；`apply_records(...)` 共享降级/落库骨架（validate 二次把关 → 缺必填降级 needs_info / 非法 skip）。`validate`/`render` 保留（render 供 comment/body、validate 供二次把关）。
- **T2 · triage**：submit_triage 工具 input_schema = `agent_contract.dispositions_input_schema()`，设为 **stop tool**；binding `submit_triage(dispositions, agent_state=None)` **返回 `{"dispositions": dispositions}`**；`_run_agent` 返回 `agent.run` 的返回值，`triage_once` 对其 `json.loads` 取 `dispositions`（parse 失败 = no-op 兜底）；`_apply` 简化（nexau 已校验，直接读 `issue`/`disposition`/`fields`/`of`，删 `_normalize_dispositions`/`_parse_dispositions`/`_disposition_of`/`_issue_num`/`_accept_fields` 与 `output_contract_schema`）；**per-kind 必填仍由 driver `schema_validate(section=triage)` 二次把关**（json_schema 只锁 union 字段、不表达 per-kind 条件必填）；systemprompt 去手抄 JSON、改「调 submit_triage」；max_iterations 给足 + 保留「未调 submit → no-op」兜底。
- **T3 · synthesizer**：submit_rfcs 工具 input_schema = `agent_contract.rfc_input_schema()`，stop tool；binding 返回 `{"proposals": proposals}`；`propose_once` 对 `agent.run` 返回 `json.loads` 取 `proposals` → 落 RFC + supersede；删 `_parse_proposals`/`_unwrap_result` 解析用途；systemprompt 去手抄 fields。
- **单一真源落法**（二选一，T2 先定）：① 程序化——`Tool.from_dict({...,"input_schema": agent_contract.X()}, binding=…)` + `agent.add_tool()`（真单源、无 yaml 副本，但 stop_tool 标记方式待 T2 实跑确认）；② 静态 `.tool.yaml`（**用 Write 工具写、UTF-8 安全**）+ drift-guard 测试断言 `yaml["input_schema"] == agent_contract.X()`（yaml 为受测守护的生成副本）。任一都保证契约与 SCHEMAS 同源。

**DAG**：T1 → T2、T1 → T3（T2/T3 于 T1 后可并行）。文件按 task 单一归属、互不重叠。

**Non-goal**：不改闭环 a/d1/d2/b/c 语义与分工；不改 dev 领取/预算/carryover；不引 benchmark；不做 triage/synthesize 的分片调度（那是另一条扩展性线，可后续 spec）。

## Drawbacks

- 依赖 nexau 工具层 jsonschema 校验与 ToolValidationError→重试的实际行为——需在 T2/T3 实跑确认「校验失败会把错误回灌给模型重试」而非直接中断；若不满足，退回「submit 工具 + T1 共享宽容兜底」（仍比现状 2 次调用干净）。
- 一次较大重构，牵动 4 处产出路径；靠 3 个 task 文件不重叠 + 每 task 测试绿 + 行为等价（四路 disposition / RFC covers 不变）控风险。
- 去掉 USER 段是「承认现状」，若将来真想让用户填模板，需另设计（但那与「体感真实」相悖）。

## Rationale and alternatives

- **为何 submit-tool 原生而非保留约束解码**：nexau 本就在工具层强校验，submit-tool 一次调用即得合规结构；约束解码是第二次 LLM 调用去补格式，既贵又多一处可漂。前者严格更优、且契约与 schema 同源。
- **为何删 USER 段而非补接线**：真实 persona 写自由报告，强制模板既不真实也没接线价值；triage 的规范化产物才是 dev 的 Definition of Ready，schema 聚焦于此。
- **备选**：只统一 triage/synthesizer 两侧的解析、保留约束解码——治标不治本，仍两次调用、仍与 USER 段割裂。
- **备选**：保留括号扫描做统一兜底，不上 submit-tool——省事但放弃「发出即校验」，漂移仍需事后救。

## Prior art

- spec-0025 立了 issue_schema 与 USER/TRIAGE 分段、triage/synthesize 拆分；本 spec 收敛其未接线的一半、统一产出机制。
- spec-0024 的 god-view 渐进下钻示范了「让工具承担结构、按需取用」的思路；submit-tool 是同一思路用在产出侧。
- nexau 工具 input_schema + jsonschema 校验（`archs/tool/tool.py`）是本方案的能力基础。

## Unresolved questions

三个原 Unresolved 已在生产环境的 nexau 上**实证钉死**（供 T2/T3 直接照做，退路不必走）：

1. **工具层强校验 = 有**（`archs/tool/tool.py` `Tool.validate_params` 里 `jsonschema.validate`）。实测：
   非法 enum、缺必填、嵌套项非法 enum、嵌套项多余键（additionalProperties）→ **全拒**。**⚠️ 关键坑**：
   `schema_params` 会先把**顶层**未声明键滤掉再校验 → **顶层多余键不拒**（静默丢）。故 payload 必须放
   在**嵌套数组**里（`{dispositions:[item…]}`），item 级设 `additionalProperties:false + required + enum`
   → 漂移字段（triage_decision 等）在 item 级被拒。**本 spec 的 agent_contract 生成的 schema 正是这个
   形态**（T1 已就绪）。
2. **校验失败会回灌重试**：这版 nexau **无 ToolValidationError 类**，校验失败抛 `ValueError("Invalid
   parameters for tool …")`；executor 把工具异常 catch → 组 `ToolResultBlock(is_error=True)` → 喂回模型
   → 下一轮重试。重试上限 = agent `max_iterations`（无专门计数器）。**故：max_iterations 给足 + 保留
   「agent 没调 submit → 本轮 no-op/兜底」那道最小安全网**。⚠️ driver **别 import/catch
   ToolValidationError**（不存在）；重试是 `agent.run` 内部自动的。
3. **submit 参数走 stop-tool 返回**：`executor.py` stop tool 触发 → stop_tool_result → `agent.run()` 的
   返回值（非字符串会被 JSON 序列化）。**接口**：submit 工具 binding **返回校验后的 params(dict)** →
   成为 `agent.run` 返回 → driver 对返回值 `json.loads` 取 `dispositions`/`proposals`。原生路径、无 side-channel。

仍待 T2/T3 收口：`_norm_label`/`render`/`validate` 哪些下线（render 供 comment/body 仍需保留）。

## Future possibilities

- 同一 agent_contract 机制可推广到用户 sim 的 issue 产出（若将来要半结构化）与 dev 的产出。
- 与「triage/synthesize 分片调度」扩展性 spec 叠加：submit-tool 每片提交、契约不变。
- input_schema 可继续收紧（per-kind 条件必填用 oneOf 表达），把二次把关也上移到工具层。

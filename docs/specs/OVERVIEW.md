# Spec 总览（OVERVIEW）

> 本文件由 `spec render` 自动生成，请勿手工编辑（Spec-0014/T3）。

## 全局看板

| 组 | 任务 | 标题 | 状态 | 依赖 | 涉及文件 |
|----|----|----|----|----|----|
| 0001 | 0001/T1 | 用户侧数据模型 | pending | — | src/auto_designer/user_side/models.py<br>tests/user_side/test_models.py |
| 0001 | 0001/T2 | Harness 对话接口 | pending | T1 | src/auto_designer/harness/interface.py<br>tests/harness/test_interface.py |
| 0001 | 0001/T3 | 用户 agent 驱动器 | pending | T1, T2 | src/auto_designer/user_side/user_agent.py<br>tests/user_side/test_user_agent.py |
| 0001 | 0001/T4 | 会话编排 runner | pending | T1, T2, T3 | src/auto_designer/user_side/session.py<br>tests/user_side/test_session.py |

## 跨 feature 关系图

```mermaid
graph LR
    subgraph G0001[0001 user-agent-harness-usage]
        n0001_T1["T1 用户侧数据模型"]
        n0001_T2["T2 Harness 对话接口"]
        n0001_T3["T3 用户 agent 驱动器"]
        n0001_T4["T4 会话编排 runner"]
    end
    n0001_T2 --> n0001_T1
    n0001_T3 --> n0001_T1
    n0001_T3 --> n0001_T2
    n0001_T4 --> n0001_T1
    n0001_T4 --> n0001_T2
    n0001_T4 --> n0001_T3
```

## 文件冲突报告

无跨组文件冲突。

## 各 feature 详情

### 0001 用户 agent 使用 harness 的最小链路（issue #0）

```mermaid
graph LR
    nT1["T1 用户侧数据模型"]
    nT2["T2 Harness 对话接口"]
    nT3["T3 用户 agent 驱动器"]
    nT4["T4 会话编排 runner"]
    nT1 --> nT2
    nT1 --> nT3
    nT2 --> nT3
    nT1 --> nT4
    nT2 --> nT4
    nT3 --> nT4
```

演化图：

```mermaid
graph LR
    v_T1_1["T1 v1"]
    v_T2_1["T2 v1"]
    v_T3_1["T3 v1"]
    v_T4_1["T4 v1"]
    classDef st_pending fill:#eeeeee;
    class v_T1_1 st_pending;
    class v_T2_1 st_pending;
    class v_T3_1 st_pending;
    class v_T4_1 st_pending;
```

---
name: lark-cli
description: Use the Lark/Feishu CLI to read documents, send messages, query calendars, manage tasks, fetch spreadsheet data, and interact with the Lark platform. Use when the task involves Lark/Feishu operations — reading meeting minutes, sending notifications, fetching docs, or querying enterprise data.
compatibility: Requires Node.js (npm), network access, and authenticated Lark/Feishu account.
metadata:
  author: larksuite
  source: https://github.com/larksuite/cli
---

# Lark CLI

Lark/Feishu 平台的官方命令行工具，覆盖 12 个业务域（消息、日历、文档、表格、数据库、任务、邮件、审批等），200+ 命令。

## Install

```bash
npm install -g @larksuite/cli
```

验证安装：
```bash
lark-cli --version
```

## Auth

首次使用需要认证：

```bash
# 1. 初始化配置（交互式，配置 app credentials）
lark-cli config init

# 2. 登录
lark-cli auth login

# 3. 检查登录状态
lark-cli auth status
```

认证凭证安全存储在系统 keychain 中。

**检查特定权限**：
```bash
lark-cli auth check --scope <scope-name>
lark-cli auth scopes  # 列出所有可用权限
```

**切换身份**：
```bash
lark-cli <command> --as user   # 以用户身份执行
lark-cli <command> --as bot    # 以机器人身份执行
```

## 命令结构

三层架构，按需选择：

### 快捷命令（+前缀）— 最常用

```bash
# 发消息
lark-cli im +messages-send --chat-id "oc_xxx" --text "Hello"

# 查日历
lark-cli calendar +agenda

# 创建文档
lark-cli docs +create --title "Report" --markdown "# Content"

# 创建任务
lark-cli tasks +create --title "Task" --due-date "2025-01-01"

# 创建表格
lark-cli sheets +create --title "Data"
```

### API 命令 — 完整能力

```bash
# 消息
lark-cli im messages list --chat-id "oc_xxx" --format json
lark-cli im messages get --message-id "om_xxx"
lark-cli im chats create --name "Group" --user-ids "ou_xxx,ou_yyy"

# 日历
lark-cli calendar calendars list --format json
lark-cli calendar events create --calendar-id "xxx" --summary "Meeting"
lark-cli calendar freebusy query --user-id "ou_xxx" --start-time "2025-01-01T09:00:00Z" --end-time "2025-01-01T18:00:00Z"

# 文档
lark-cli docs documents create --title "Doc" --folder-token "fldcnxxx"
lark-cli docs documents read --token "doccnxxx"
lark-cli docs documents search --query "keyword"

# 表格
lark-cli sheets values read --spreadsheet-id "shtcnxxx" --range "Sheet1!A1:Z100"
lark-cli sheets values write --spreadsheet-id "shtcnxxx" --range "Sheet1!A1" --values '[["a","b"],["c","d"]]'
lark-cli sheets values append --spreadsheet-id "shtcnxxx" --range "Sheet1" --values '[["new","row"]]'

# 数据库 (Base)
lark-cli base tables list --app-token "bascnxxx"
lark-cli base records read --app-token "bascnxxx" --table-id "tblxxx"
lark-cli base records create --app-token "bascnxxx" --table-id "tblxxx" --fields '{"Name":"test"}'

# 任务
lark-cli task tasks list --format json
lark-cli task tasks create --title "Task" --due '{"timestamp":"1735689600"}'

# 联系人
lark-cli contact users search --query "张三"
lark-cli contact users get --user-id "ou_xxx"

# 邮件
lark-cli mail messages list --format json
lark-cli mail messages send --to "user@example.com" --subject "Subject" --body "Content"

# Wiki
lark-cli wiki spaces list
lark-cli wiki nodes create --space-id "xxx" --title "Page"

# 会议纪要
lark-cli minutes minutes list --format json

# 审批
lark-cli approval tasks query --format json
lark-cli approval tasks approve --task-id "xxx"

# 文件
lark-cli drive files upload --file-path "/path/to/file" --parent-token "fldcnxxx"
lark-cli drive files download --file-token "boxcnxxx" --output "/path/to/output"
lark-cli drive files search --query "keyword"
```

### 原始 API — 直接调用任意 endpoint

```bash
lark-cli api GET /open-apis/calendar/v4/calendars
lark-cli api POST /open-apis/im/v1/messages --body '{"receive_id":"ou_xxx","msg_type":"text","content":"{\"text\":\"hello\"}"}'
```

## 输出格式

```bash
--format json       # JSON（默认，适合程序解析）
--format ndjson     # 逐行 JSON（适合管道处理）
--format table      # 表格（适合人类阅读）
--format csv        # CSV
```

## 分页

```bash
--page-all          # 自动翻页获取全部
--page-limit 5      # 最多翻 5 页
--page-delay 500    # 页间延迟 500ms
```

## 预演模式

```bash
lark-cli docs +create --title "Test" --dry-run
# 预览操作，不实际执行
```

## 常用场景

### 读取飞书文档内容
```bash
# 搜索文档
lark-cli docs documents search --query "周报" --format json

# 读取文档
lark-cli docs documents read --token "doccnxxx" --format json
```

### 发送消息通知
```bash
# 发送文本消息到群
lark-cli im +messages-send --chat-id "oc_xxx" --text "构建完成，请查看结果"

# 发送富文本
lark-cli im +messages-send --chat-id "oc_xxx" --content '[{"tag":"text","text":"Status: "},{"tag":"a","text":"Link","href":"https://example.com"}]'
```

### 获取会议纪要
```bash
lark-cli minutes minutes list --format json
# 获取特定会议的摘要和转录
```

### 查询表格数据
```bash
lark-cli sheets values read --spreadsheet-id "shtcnxxx" --range "Sheet1!A1:Z100" --format json
```

### 查询审批流程
```bash
lark-cli approval tasks query --format json
```

## 注意事项

- 所有写操作建议先用 `--dry-run` 预览
- 大量数据使用 `--page-all` 自动翻页
- 输出优先使用 `--format json` 便于解析
- 认证状态可用 `lark-cli auth status` 检查
- 权限不足时用 `lark-cli auth login --domain <domain>` 补充授权

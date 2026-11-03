---
name: lark-cli
description: Use the Lark/Feishu CLI to read documents, send messages, query calendars, manage tasks, fetch spreadsheet data, and interact with the Lark platform. Use when the task involves Lark/Feishu operations — reading meeting minutes, sending notifications, fetching docs, or querying enterprise data.
compatibility: Requires Node.js (npm), network access, and authenticated Lark/Feishu account.
metadata:
  author: larksuite
  source: https://github.com/larksuite/cli
---

# Lark CLI

The official CLI for the Lark/Feishu platform, covering 12 business domains (messages, calendars, documents, spreadsheets, databases, tasks, mail, approvals, and more) with 200+ commands.

## Install

```bash
npm install -g @larksuite/cli
```

Verify the installation:
```bash
lark-cli --version
```

## Auth

Authenticate before first use:

```bash
# 1. Initialize configuration (interactive; configure app credentials)
lark-cli config init

# 2. Sign in
lark-cli auth login

# 3. Check authentication status
lark-cli auth status
```

Authentication credentials are stored securely in the system keychain.

**Check a specific permission**:
```bash
lark-cli auth check --scope <scope-name>
lark-cli auth scopes  # List all available permissions
```

**Switch identity**:
```bash
lark-cli <command> --as user   # Run as a user
lark-cli <command> --as bot    # Run as a bot
```

## Command structure

Choose among three command layers as needed:

### Shortcut commands (+ prefix) — most common

```bash
# Send a message
lark-cli im +messages-send --chat-id "oc_xxx" --text "Hello"

# Check the calendar
lark-cli calendar +agenda

# Create a document
lark-cli docs +create --title "Report" --markdown "# Content"

# Create a task
lark-cli tasks +create --title "Task" --due-date "2025-01-01"

# Create a spreadsheet
lark-cli sheets +create --title "Data"
```

### API commands — full capabilities

```bash
# Messages
lark-cli im messages list --chat-id "oc_xxx" --format json
lark-cli im messages get --message-id "om_xxx"
lark-cli im chats create --name "Group" --user-ids "ou_xxx,ou_yyy"

# Calendar
lark-cli calendar calendars list --format json
lark-cli calendar events create --calendar-id "xxx" --summary "Meeting"
lark-cli calendar freebusy query --user-id "ou_xxx" --start-time "2025-01-01T09:00:00Z" --end-time "2025-01-01T18:00:00Z"

# Documents
lark-cli docs documents create --title "Doc" --folder-token "fldcnxxx"
lark-cli docs documents read --token "doccnxxx"
lark-cli docs documents search --query "keyword"

# Spreadsheets
lark-cli sheets values read --spreadsheet-id "shtcnxxx" --range "Sheet1!A1:Z100"
lark-cli sheets values write --spreadsheet-id "shtcnxxx" --range "Sheet1!A1" --values '[["a","b"],["c","d"]]'
lark-cli sheets values append --spreadsheet-id "shtcnxxx" --range "Sheet1" --values '[["new","row"]]'

# Database (Base)
lark-cli base tables list --app-token "bascnxxx"
lark-cli base records read --app-token "bascnxxx" --table-id "tblxxx"
lark-cli base records create --app-token "bascnxxx" --table-id "tblxxx" --fields '{"Name":"test"}'

# Tasks
lark-cli task tasks list --format json
lark-cli task tasks create --title "Task" --due '{"timestamp":"1735689600"}'

# Contacts
lark-cli contact users search --query "Zhang San"
lark-cli contact users get --user-id "ou_xxx"

# Mail
lark-cli mail messages list --format json
lark-cli mail messages send --to "user@example.com" --subject "Subject" --body "Content"

# Wiki
lark-cli wiki spaces list
lark-cli wiki nodes create --space-id "xxx" --title "Page"

# Meeting minutes
lark-cli minutes minutes list --format json

# Approvals
lark-cli approval tasks query --format json
lark-cli approval tasks approve --task-id "xxx"

# Files
lark-cli drive files upload --file-path "/path/to/file" --parent-token "fldcnxxx"
lark-cli drive files download --file-token "boxcnxxx" --output "/path/to/output"
lark-cli drive files search --query "keyword"
```

### Raw API — call any endpoint directly

```bash
lark-cli api GET /open-apis/calendar/v4/calendars
lark-cli api POST /open-apis/im/v1/messages --body '{"receive_id":"ou_xxx","msg_type":"text","content":"{\"text\":\"hello\"}"}'
```

## Output formats

```bash
--format json       # JSON (default; suitable for programmatic parsing)
--format ndjson     # Newline-delimited JSON (suitable for pipelines)
--format table      # Table (suitable for human readers)
--format csv        # CSV
```

## Pagination

```bash
--page-all          # Fetch all pages automatically
--page-limit 5      # Fetch at most 5 pages
--page-delay 500    # Wait 500ms between pages
```

## Dry-run mode

```bash
lark-cli docs +create --title "Test" --dry-run
# Preview the operation without executing it
```

## Common workflows

### Read a Feishu document
```bash
# Search for documents
lark-cli docs documents search --query "weekly report" --format json

# Read a document
lark-cli docs documents read --token "doccnxxx" --format json
```

### Send a notification
```bash
# Send a text message to a group
lark-cli im +messages-send --chat-id "oc_xxx" --text "The build is complete. Please review the results."

# Send rich text
lark-cli im +messages-send --chat-id "oc_xxx" --content '[{"tag":"text","text":"Status: "},{"tag":"a","text":"Link","href":"https://example.com"}]'
```

### Fetch meeting minutes
```bash
lark-cli minutes minutes list --format json
# Fetch a specific meeting summary and transcript
```

### Query spreadsheet data
```bash
lark-cli sheets values read --spreadsheet-id "shtcnxxx" --range "Sheet1!A1:Z100" --format json
```

### Query an approval workflow
```bash
lark-cli approval tasks query --format json
```

## Notes

- Preview write operations with `--dry-run` first.
- Use `--page-all` to paginate automatically through large datasets.
- Prefer `--format json` for parseable output.
- Check authentication with `lark-cli auth status`.
- If permissions are insufficient, use `lark-cli auth login --domain <domain>` to grant additional authorization.

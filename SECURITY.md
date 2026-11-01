# Security policy

English | [简体中文](SECURITY.zh-CN.md)

## Runtime access

This project is intended for trusted research and development environments. Agents can execute commands, modify repositories and call external model services. Delivery workflows may also merge pull requests automatically.

Configure Docker access, host tools, repository credentials and model endpoints according to the permissions each workflow needs. Restrict access to the live observation API; a publicly accessible deployment requires authentication.

## Report a vulnerability

Please use [GitHub private vulnerability reporting](https://github.com/Curry09/auto-designer/security/advisories/new) to report a security issue. If that channel is unavailable, contact a maintainer through an existing private channel to arrange a way to share the report. Keep credentials, exploit details and raw user conversations out of public issues.

A useful report includes the affected version or commit, the component involved, reproduction steps and the potential impact. Remove secrets and unrelated private content from any supporting logs or examples.

For ordinary bugs, use the [bug report template](.github/ISSUE_TEMPLATE/bug_report.md). See [Contributing](CONTRIBUTING.md) for the information to include.

## Protect experiment data

Logs and experiment artifacts may contain credentials, task source code, user conversations or private service information. Before sharing them, review their contents and remove sensitive data. Do not attach `.env` files, access tokens or unreviewed experiment archives to public reports.

Before publishing source code or release assets, maintainers should scan the Git history and release files, address the findings, and rotate any exposed credentials that remain valid. `.gitignore` does not remove sensitive data already present in Git history. The [release checklist](docs/RELEASING.md) covers these publication checks.

## Supported versions

Release notes identify the versions covered by security updates. The project currently has no separate long-term security maintenance branch or fixed response-time commitment.

---
target: terminal-bench
priority_domains: [infra-devops, systems-runtime, security, data-eng, dev-tooling]
pools:
  github: skill-profiles  # consumed by extract-github-persona (expert/competent end)
  stackoverflow: tags     # consumed by extract-stackoverflow-persona (blind/surface end)
---

# Recruitment target: Terminal-Bench

Terminal-Bench tests agents on **terminal / CLI tasks** (sysadmin, build & compile,
data pipelines, security, debugging). It is *task*-based, **not** mined from a fixed
repo set — so recruit by **skill profile** (people who live in the shell), not by a
canonical repo list. Multi-source like swe-bench: GitHub fills the expert end, SO the
blind end. The repos/tags below are *seed pools / examples*, not exhaustive.

## GitHub pool (extract-github-persona)

| Priority domain | Recruit from (seed pools) | Signal to look for in footprint |
|---|---|---|
| `infra-devops` | `ansible/ansible`, `hashicorp/terraform`, `kubernetes/kubernetes`, `prometheus/prometheus` | IaC, Dockerfiles, CI/CD, sysadmin dotfiles |
| `systems-runtime` | `llvm/llvm-project`, `rust-lang/cargo`, build toolchains, C/Rust CLI tools | Makefiles, compile/link work, low-level fixes |
| `security` | security-tooling repos, CTF writeup authors | exploit/pentest scripts, hardening, CVE work |
| `data-eng` | `dbt-labs/dbt-core`, `apache/airflow` (CLI usage), spark tooling | pipeline configs, `*-submit` / cron / batch scripts |
| `dev-tooling` / shell | `BurntSushi/ripgrep`, `junegunn/fzf`, `tmux/tmux`, `neovim/neovim`, `jqlang/jq`, `Homebrew/homebrew-core` | shell scripts, packaging/build tooling, CLI UX |

## Stack Overflow pool (extract-stackoverflow-persona)

Same domains, **low-rep askers** under these tags fill the blind/surface end (e.g.
people stuck on a bash one-liner, a Docker build, an `ssh`/permissions error).

| Priority domain | SO tags |
|---|---|
| `infra-devops` | `ansible`, `terraform`, `kubernetes`, `docker`, `linux` |
| `systems-runtime` | `c`, `rust`, `cmake`, `makefile`, `gcc` |
| `security` | `security`, `encryption`, `ssl`, `ssh` |
| `data-eng` | `airflow`, `apache-spark`, `dbt` |
| `dev-tooling` / shell | `bash`, `shell`, `command-line`, `awk`, `sed` |

## How to recruit

1. Find contributors / issue-reporters whose footprint is **ops/CLI-heavy** (shell,
   Docker, CI, Makefiles, dotfiles) rather than application source code.
2. Same **contributor ladder** rule as SWE-bench to keep D1 diverse.
3. Run **L0–L5 + the gate as usual**; `D5.area` should land in one of the priority
   domains above.

## Complementarity

SWE-bench fills *library / source-editing* domains; terminal-bench fills
*ops / systems / CLI* domains. Run both to cover both halves of the harness's user base.

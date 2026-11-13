---
number: "0085"
title: Pinned AHE Messages evaluation adapter
issue: 0
slug: ahe-messages-evaluation
summary: Evaluate the pinned upstream AHE harness through Anthropic Messages with native SDK isolation, reproducible materials, complete capture, and correct usage and failure accounting.
tasks:
  - id: T1
    title: Pin and install AHE with an isolated native SDK runtime
    status: done
    priority: P1
    depends-on: []
    files:
      - .gitignore
      - .gitattributes
      - pyproject.toml
      - backend/scripts/check_nexau_dependency.py
      - evaluation/harness/ahe.py
      - evaluation/harness/ahe_entry.py
      - evaluation/harness/ahe_bootstrap.py
      - evaluation/harness/ahe_artifact/**
      - evaluation/configuration.py
      - evaluation/preparation.py
    scope: Preserve upstream agent policy and fixed source; allow explicit AHE protocol selection and reproducible native SDK materials.
    acceptance: Changed source or patched SDK packages are rejected; AHE prepares through both existing task sources without changing their contracts.
  - id: T2
    title: Preserve Messages capture, usage and termination semantics
    status: done
    priority: P1
    depends-on: [T1]
    files:
      - evaluation/harness/fulltrace.py
      - evaluation/harness/driver.py
      - evaluation/harness/sim_driver.py
      - evaluation/usage.py
      - evaluation/harbor/grading.py
      - evaluation/tests/test_ahe.py
      - evaluation/tests/test_ahe_messages.py
      - evaluation/tests/test_ahe_materials.py
    scope: Replay native signed thinking; preserve full tool and HTTP records, cache-aware usage and task-owned timeouts without additional retries.
    acceptance: Real local shell and HTTP fixtures cover streaming, complete responses, follow-up feedback, partial streams, output limits and source/runtime tampering.
  - id: T3
    title: Publish bilingual instructions and a validated configuration example
    status: done
    priority: P1
    depends-on: [T1, T2]
    files:
      - README.md
      - README.zh-CN.md
      - THIRD_PARTY.md
      - THIRD_PARTY.zh-CN.md
      - evaluation/README.md
      - evaluation/README.zh-CN.md
      - evaluation/docs/harbor.md
      - evaluation/docs/harbor.zh-CN.md
      - examples/evaluation/ahe-messages.yaml
    scope: Document source/runtime preparation, credentials, Messages parameters, supported user modes and upstream attribution.
    acceptance: Configuration and package installation are verified offline; private campaign records and credentials are absent from the change.
---

# 0085 · Pinned AHE Messages evaluation adapter

<!-- Maintained by the spec tool: frontmatter is the structured source (including the Task DAG); the body is the group-level, nine-section RFC overview. -->

## Summary

Add the fixed upstream AHE evolved harness as an independent evaluated agent through the existing stdio transport, including Anthropic Messages and native SDK isolation.

## Motivation

The formal Messages campaign has a working adapter outside this repository. Public evaluation must support that agent without importing private campaign files, restoring old package names, or removing current task-source profiles.

## Guide-level explanation

Materialize AHE with `python -m evaluation.harness.ahe --destination ../harnesses/ahe --build-runtime`. Select `harnesses: [ahe]`, set `actor.api_type: anthropic_chat_completion` and keep `execution.time_adaptation: false`. Existing direct and reply-follow-up user modes continue to use task-owned budgets and grading.

## Reference-level explanation

T1 pins `china-qijizhifeng/agentic-harness-engineering` at `182ea06e578df7b1d503eca537503c1e4c5a8a58`, preserving prompts, tools, middleware, memory and the 300-iteration limit. It adds only transport, operating-parameter overrides and observation hooks. AHE uses NexAU `28511d9f0362191a6c378fd441b2be55309a9e32`; its complete package fingerprint prevents reuse of a patched framework wheel. Runtime files have individual hashes and retain licenses. `task_source: harbor_index` and `task_source: harbor` retain their current preparation paths.

T2 distinguishes Messages `max_tokens` termination, merges streaming usage start/delta/cache counts, and marks streams without message_stop incomplete. Signed thinking is replayed by the native SDK without rewriting assistant history. It adds no continuation prompts, score retries or time-budget correction. Detailed raw observations remain private; user feedback excludes internal reasoning. Exact declared missing task artifacts retain the current grading classification.

T3 provides synchronized English/Chinese entry documentation and a sanitized sample. The local fixture tests exercise the actual agent, HTTP serialization and shell tools without E2B or paid models. The task graph is T1 → T2 → T3; each task owns the files listed above.

## Drawbacks

One additional pinned third-party source and native SDK kit must be maintained. Full model and infrastructure reproducibility still requires the documented provider and task materials.

## Rationale and alternatives

A narrow adapter preserves the current framework and makes the experimental agent identity auditable. Replacing the evaluation directory would regress task-source support. Reusing a modified SDK would change the evaluated agent. Binary SDK kits are generated and checked rather than committed to Git.

## Prior art

The frozen Messages campaign supplies the transport and regression fixtures. Existing Meta-Harness integration supplies the pattern for pinned third-party attribution; current stdio evaluation supplies budget and collection contracts.

## Unresolved questions

No new interaction policy is introduced. Separate campaign repetitions and published result bundles remain independently recorded experiments.

## Future possibilities

Additional upstream agents or protocols can follow this material contract after separate validation.

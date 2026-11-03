---
number: "0046"
title: "Isolated validation handoff of frozen design artifacts to OpenAgents"
issue: 0
slug: frozen-openagents-validation-handoff
summary: "Copy the frozen requirements-surface summary or a read-only Gitea snapshot into a brand-new validation repository, selectively retain delivery tokens, and generate a non-overwritable manifest; then start an isolated vigil with explicit Anthropic-compatible gateway configuration, ensuring the experiment is reusable and does not contaminate the source."
tasks:
  - id: T1
    title: "Fresh-Target and Immutable Manifest Contract"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - docs/specs/0046-frozen-openagents-validation-handoff.md
    scope: "Define handoff invariants including read-only source, a target that must not already exist, a manifest that must not be overwritten, local verifiable errors occurring before external mutations, stable issue numbers, and credentials not being written to disk."
    acceptance: "Complete nine-section Spec; source=target, missing issue, malformed summary, and existing manifest all fail closed; spec validate/render/graph and pytest pass."
  - id: T2
    title: "Materialize the Frozen Summary as a Validation Repository"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - tools/dev/delivery/prepare_openagents_from_summary.py
      - backend/tests/test_prepare_openagents_from_summary.py
    scope: "Preflight the contiguous issue snapshot and harness directory; exclude Git and bytecode runtime artifacts during copying; create main in a fresh Gitea repository and restore issue states and labels under their original numbers; write a manifest containing the source/main SHA and delivery selection."
    acceptance: "Validate all local inputs before creating the repository; do not modify the source directory or summary; target issue numbers, states, labels, and delivery selection match; manifest atomicity boundaries are explicit and it contains no credentials; tests and a record of a real fresh-target run pass."
  - id: T3
    title: "Selective Delivery Copy of a Read-Only Gitea Snapshot"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - tools/dev/delivery/prepare_openagents_validation.py
      - backend/tests/test_prepare_openagents_validation.py
    scope: "Read and validate the source main branch and issue/comment snapshot first, then create a fresh target; when copying Git, remove tracked bytecode; retain the openagents token only for issues explicitly selected with --deliver, while preserving other facts and comments."
    acceptance: "Source and target must differ; the selected issue must exist; preflight failures do not create the target; main/issue/comment/state are copied consistently and the source remains unchanged; the manifest records the selection and SHA; tests and a real replay record pass."
  - id: T4
    title: "Isolated Vigil Startup and Gateway Protocol Conversion"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
      - T3
    relates-to: []
    parallel: false
    files:
      - tools/dev/delivery/run_openagents_validation.py
      - backend/tests/test_run_openagents_validation.py
    scope: "Convert the shared WIS env into Anthropic-compatible base/auth/model configuration, validate the config and concurrency, and start vigil under an independent container name; pass Gitea/model credentials only through the subprocess env, and inject both cases of proxy and no_proxy variables completely."
    acceptance: "Environment values containing spaces/quotes can be parsed; /v1 removes only the trailing version segment; missing fields and invalid concurrency fail before docker runs; the command contains no secret values; container network/read-only mount/proxy parameters are complete; pytest and ruff pass."
---

# 0046 · Isolated Validation Handoff for Frozen Design Artifacts to OpenAgents

<!-- This file is maintained by the spec tool: the frontmatter contains structured source data (including the tasks DAG), and the body is the group-level nine-section rust-RFC overview. -->

## Summary

Provide a frozen handoff path exclusively for experimental validation: create a new target repository from an offline design summary or an existing Gitea experiment snapshot, copy the fixed main branch, issues, comments, and states, and retain delivery tokens only for explicitly selected candidates using `openagents`. The source must always be read-only, the target must not exist, and the manifest must be a new file; any error discoverable locally or during the read-only phase must fail before the target is created.

After preparation is complete, a standalone startup script converts the shared WIS configuration into the Anthropic-compatible environment required by Claude Code, then starts vigil with a dedicated container name, read-only configuration mounts, and an isolated network. Credentials pass only through the subprocess environment and do not enter command arguments, the manifest, or the target repository. This group validates the implementation feasibility of frozen design artifacts, does not reconnect to the production requirements surface, and does not automatically merge experimental results.

## Motivation

After requirements-surface roles, Prompts, or schemas change, already-expensive user interactions and proposals need to be reused to revalidate OpenAgents without rerunning the user model, modifying the original experiment repository, or reusing residual PR/label state. Restoring labels directly in the old repository makes the before-and-after experiments indistinguishable; manual copying can easily omit closed state, comments, the main SHA, or delivery selections.

The previous restoration script created the target repository before validating the selected issues, so invalid input left partial artifacts; copying a harness containing `.git` could also inherit source history and remotes. If gateway startup manually assembles the environment, the `/v1` path and Anthropic client append rules can easily produce duplicated path segments. An experiment-tool boundary is needed that fails closed, uses a fresh target, is auditable, and does not persist secrets.

## Guide-level explanation

There are two input entry points:

```text
frozen summary + harness dir ── prepare_from_summary ─┐
                                                     ├─ fresh Gitea target + manifest
read-only Gitea source ───── prepare_validation ─────┘
                                                                  │
WIS env + model + config ───── run_openagents_validation ─────────┘
                                                                  ▼
                                                        isolated vigil container
```

The summary entry point is suited to offline role replay; the Gitea entry point is suited to selecting 1..n delivery candidates from the complete facts of a given round. Both first reject an existing manifest and an existing target. The Gitea entry point copies all issue facts, but removes delivery tokens from issues that were not selected; it does not delete issues, comments, or source labels. The manifest records the source, target, main SHA, issue snapshots, delivery issues, and `openagents_started=false`; startup occurs separately.

## Reference-level explanation

The summary must contain a list of issue objects, with numbers consecutive from 1 and unique, title/body as strings, labels as an array of strings, and state restricted to open/closed; the harness directory must exist. These checks occur before any Gitea API call. When copying the harness, exclude `.git`, `__pycache__`, and `*.pyc`, initialize a fresh main branch in a temporary directory, and create issues by number after pushing; numbering drift fails immediately.

The Gitea snapshot entry point first constructs a source tracker, reads all issues and the selection set, and validates that source and target differ, numbering is valid and unique, and all selected issues exist; only then does it create the target. Git clones the source main branch, removes tracked bytecode, and adds generic `.gitignore`, saving the cleanup in a new commit if needed, then switches origin to the target and pushes. Issues, comments, and closed state are restored by number, and only selected issues retain `openagents`.

The startup script requires the config directory to contain `openagents.yml`, parallel >= 1, and WIS env containing base/key. It removes the segment only when the URL path ends with `/v1`, avoiding accidental changes to an intermediate path; the converted result is supplied through the environment as `ANTHROPIC_BASE_URL/AUTH_TOKEN/MODEL`.
Docker commands list environment variable keys only and contain no values; the configuration and entrypoint are mounted read-only, and vigil uses an isolated network with complete case-preserving proxy settings.

## Drawbacks

External mutations still cannot be made transactional: if git push or writing the Nth issue fails after target creation succeeds, a partial target repository may remain. This group guarantees that precheckable errors produce no mutation, but does not claim atomicity across Gitea and Git requests. The consecutive-number requirement limits summary inputs to arbitrary issue subsets; this is required to reliably restore original numbering. Copying the complete repository and all issues also increases time and storage use.

## Rationale and alternatives

A fresh target was chosen instead of restoring the original repository state to obtain experimental isolation and clear auditing. The manifest is not overwritten, preventing a later run from erasing the source information from an earlier run. Production `start_vigil` is not called directly because validation requires an independent repository, model, container name, and configuration directory; the same environment parser, image, and entrypoint are reused to avoid protocol divergence.

The temporary owner/architect restoration scripts are not included in this group: they modify existing repositories and lack complete before-state snapshots, so they are suitable only for retention as incident evidence. Secrets are not written to temporary environment files or the manifest; the subprocess environment is the sole credential channel.

## Prior art

The replay tools in Specs 0042/0043 freeze requirements-surface inputs, Prompt hashes, and role artifacts, and stop before OpenAgents; this group continues from that boundary. Specs 0032/0033 define Gitea delivery tokens and vigil container isolation, and Spec 0045 provides OpenAgents/NexAU dual-pin images. This group does not change those production contracts; it provides only experimental copying and startup adaptation.

## Unresolved questions

Gitea lacks cross-repository clone/issue batch transactions; whether to automatically delete a fresh target after failure in the future requires separate authorization because deleting a remote repository is destructive. The current manifest is written at successful completion, so external failures leave remote evidence but no local failure manifest; whether to add a per-stage journal requires a later design.

## Future possibilities

A dry-run plan, source/target snapshot hashes, container image digest, OpenAgents/NexAU SHA, and a per-stage journal could be added to provide complete experimental provenance. If the forge provides a repository template or transactional import API, per-request copying could be replaced, but the invariants of a read-only source, fresh target, explicit selection, and credentials not being persisted to disk must remain.

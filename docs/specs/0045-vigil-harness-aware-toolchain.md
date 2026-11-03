---
number: "0045"
title: "Vigil Harness-aware Development Toolchain"
issue: 0
slug: vigil-harness-aware-toolchain
summary: "Build a non-root vigil image with explicit dual OpenAgents/NexAU checkout pins, providing the real source code and testing tools needed for internal harness orchestration; build-time dependencies, the Claude version, proxies, and runtime configuration are all explicit and auditable."
tasks:
  - id: T1
    title: "Toolchain Boundaries and Dual-Pin Contract"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - docs/specs/0045-vigil-harness-aware-toolchain.md
    scope: "Define dual checkout pins for OpenAgents delivery orchestration and the NexAU harness runtime, read-only source visibility, non-root execution, secure credentials, and the boundaries of local deployment overrides; do not change the OpenAgents repository source code."
    acceptance: "The nine-section Spec is complete; the boundaries between production capabilities, experimental branches, and local proxy parameters are explicit; spec validate/render/graph pass."
  - id: T2
    title: "Dual-Checkout Image and Read-Only NexAU Toolchain"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/deploy/vigil/Dockerfile
    scope: "build.sh validates the OpenAgents/NexAU checkouts and builds through a named context; the image installs both projects without build isolation, retains read-only /opt/nexau-src, installs ruff/pytest, pins and verifies the Claude Code version, and runs as uid 1000."
    acceptance: "Missing arguments or incorrect checkouts fail closed; docker build arguments and both pins are auditable; OpenAgents/NexAU/ruff/pytest/Claude are available in the container, NexAU source code is not writable, and the uid is non-root; shell and pytest tests pass."
  - id: T3
    title: "Explicit Build Package Index, Version, and Proxy Configuration"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - backend/deploy/vigil/build.sh
      - backend/tests/test_vigil_build.py
    scope: "The PIP index and Claude version have overridable defaults; host HTTP(S)/NO_PROXY values are passed only as build args, without embedding credentials or local IP addresses; local checkouts use preinstalled build backends to avoid repeated network access in isolated builds."
    acceptance: "Defaults are stable and can be overridden through VIGIL_PIP_INDEX_URL/VIGIL_CLAUDE_CODE_VERSION; the build command does not expand or log secrets; there are no hardcoded host paths/IP addresses; shell tests and image builds pass."
  - id: T4
    title: "Runtime Entry Point Wiring and Configuration Precedence"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T2
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/experiment/controllers/ordinary.py
      - backend/tests/test_run_vigil.py
    scope: "The missing-image message includes dual-checkout usage instructions; the container receives both uppercase and lowercase HTTP(S)_PROXY/NO_PROXY variables; explicit command environment configuration takes precedence over the repository .env; existing keep-alive, reuse, stop, and credential isolation behavior remains unchanged."
    acceptance: "docker run arguments are complete and do not leak credentials; explicit environment settings are not overridden by .env; missing-image instructions are actionable; test_run_vigil, ruff, and a real-container smoke test pass."
---

# 0045 · Vigil Harness-Aware Development Toolchain

<!-- This file is maintained by the spec tool: the frontmatter is structured source data (including the tasks DAG), and the body is a group-level, nine-section Rust RFC overview. -->

## Summary

Expand the vigil image from “a delivery container that only installs OpenAgents” into a development toolchain that understands the harness’s actual runtime foundations: accept separate OpenAgents and NexAU checkouts at build time, install both, and retain a read-only `/opt/nexau-src` so implementation, review, and testing roles can verify harness internals without modifying or vendoring NexAU. The commits of the two repositories serve as independently auditable pins.

The image continues to run as a non-root user, and credentials are injected only at runtime. The Claude Code version, Python package index, and build proxy are all explicitly overridable configurations; local projects use the preinstalled build backend and `--no-build-isolation` to avoid repeatedly creating networked build environments when installing each checkout. `run.py` provides build guidance for the two checkouts, a complete proxy environment, and a deterministic rule that “explicit process configuration takes precedence over the repository’s .env”. The host proxy IP, port, and a particular experiment’s model are outside this Spec.

## Motivation

Harness v0’s execution and agent definitions are based on NexAU. With only the OpenAgents source and Claude CLI, vigil can modify ordinary product files but cannot run harness tests or check the NexAU API; implementers therefore have to guess at the tracer, AgentConfig, and tool binding, and reviewers cannot verify architectural changes. This is not about making the delivery workflow modify NexAU; it is about giving it read-only technical context consistent with the system being developed, at a fixed version.

An earlier Dockerfile allowed pip to create an isolated build environment each time it installed from a local checkout, potentially downloading hatchling, setuptools, and wheel repeatedly over the network. The Claude native installer also did not pin a version, so rebuilding the same commit could produce a drifting toolchain. WSL/container environments also have proxy variables in both cases; injecting only `HTTPS_PROXY` can cause some tools to connect directly and fail. Finally, the repository’s `.env` once overrode values explicitly injected by the startup command, producing counterintuitive configuration precedence when temporarily switching gateways or models.

## Guide-level explanation

The build entry point explicitly accepts two checkouts:

```text
build.sh <OpenAgents checkout> <NexAU checkout>
             │                    │
             │ docker context     │ named context: nexau
             └─────────┬──────────┘
                       ▼
           ahe-beta-vigil:latest
             ├─ openagents CLI
             ├─ claude (fixed version)
             ├─ nexau package + /opt/nexau-src (read-only)
             ├─ ruff / pytest
             └─ USER vigil (uid 1000)
```

`VIGIL_PIP_INDEX_URL` and `VIGIL_CLAUDE_CODE_VERSION` can override the defaults. The build inherits the host’s proxy variables in both cases as Docker build args, but does not write credentials into the image. At runtime, `run.py` passes `HTTP_PROXY/HTTPS_PROXY` and its lowercase form to the container; the internal Gitea address is added to `NO_PROXY/no_proxy`. LLM configuration already present in the startup command’s environment remains unchanged; the repository’s `.env` only fills missing keys.

## Reference-level explanation

`build.sh` performs fail-closed shape validation on both paths: each must have `pyproject.toml`, and their project names must be `openagents` and `nexau`, respectively. Docker uses OpenAgents as the primary context and passes the second repository through `--build-context nexau=<path>`, without copying it to a shared parent directory. The build completion message prints the short SHA for each checkout; non-Git directories are explicitly marked rather than assigned fabricated versions.

The Dockerfile installs hatchling, setuptools, and wheel first, then installs the local projects with `--no-build-isolation`. The NexAU checkout remains at `/opt/nexau-src`, and all write permissions are removed after installation; the runtime user with uid 1000 can only read it. The build verifies key APIs by importing `Agent/AgentConfig/Span/SpanType`. The Claude installer receives an explicit version and verifies it with `claude --version`; ruff/pytest are installed during image build, so runtime does not need to access a package index.

Preflight errors from `run.py` must provide both checkout arguments. Container startup retains the mounts and credential boundaries from Spec 0033, adding only proxy variables in both cases; the Gitea token, Anthropic credentials, and model gateway credentials are passed only through env. `_apply_env_defaults` uses `os.environ.setdefault` and is shared by the generic entry point and the SWE-bench closed-loop entry point, ensuring command environment > repository `.env`.

This Spec does not own the local upstream in `egress-proxy.conf`. The WSL host address, proxy port, and current API allowlist are deployment overrides and should be kept separate from the reusable toolchain at submission time; a general-purpose repository must not pin a personal network topology.

## Drawbacks

Installing NexAU and including its source increases the image size, while the two checkouts add build inputs and pin-management costs. Keeping the source read-only still lets the Agent read more implementation details, so role Prompts and evidence budgets must continue to limit investigations from scratch; this group provides the capability only and does not authorize unlimited reading. Pinning the Claude version reduces drift but requires explicit upgrade maintenance.

## Rationale and alternatives

Choose a local checkout pin rather than installing NexAU only from a PyPI wheel, because the harness may depend on unreleased interfaces and reviewers also need to inspect the source; a read-only checkout better respects repository boundaries than allowing the Agent to modify NexAU. Choose a Docker named context rather than copying both repositories into a temporary aggregation directory, avoiding extra assets and unclear provenance.

Do not vendor NexAU into OpenAgents or Auto Architect; the three repositories continue to evolve independently. Do not allow runtime pip installation, because egress usually permits only model and forge services, and it would undermine reproducibility. Do not write the host proxy into the Dockerfile: the proxy is supplied only as a build/run parameter.

## Prior art

Spec 0033 establishes the vigil non-root container, credential isolation, and egress boundaries; this group extends tool capabilities without weakening containment. Spec 0040 opens the Spec/implementation stages in OpenAgents and keeps vigil resident; this group provides implementers with the actual harness dependencies. Spec 0041 still treats developer usage as capability-dependent; installing NexAU does not automatically grant the OpenAgents per-call Token protocol.

## Unresolved questions

The current image retains both an installed copy of OpenAgents and its build-context source, while for NexAU only the source is explicitly retained; whether a stable, read-only audit interface for `/opt/openagents-src` is also needed is for OpenAgents itself to decide. The image digest and the two Git SHAs are not yet recorded in a unified provenance manifest; this could be a later enhancement before release, but should not be inferred by parsing image logs.

## Future possibilities

A machine-readable toolchain manifest could record the base image digest, OpenAgents/NexAU SHA, and Claude/ruff/pytest versions, and be displayed read-only when vigil starts. The build could use a wheel cache or a multi-stage image to reduce size; any cache must preserve the two pins and the invariants of non-root execution, read-only source, and no credentials in the image.

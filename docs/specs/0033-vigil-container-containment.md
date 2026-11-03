---
number: "0033"
title: "Delivery-surface container containment: a vigil-specific container (zero host mounts, self-cloning inside the container) + egress proxy allowlist + observation cursor tracking origin/main"
issue: 0
slug: vigil-container-containment
summary: "After the spec-0032 route change, the delivery-surface coding agent is the out-of-process claude CLI (bypassPermissions), which the in-process workspace_jail from the nexau era cannot reach. When run bare on WSL/the host, the nested agent can read the entire filesystem (the orchestration repository and data/sessions overfitting channel), with unrestricted network egress. Existing safeguards (credential isolation/boundary hooks/repo_guard tripwires) only govern “what was changed and where it was pushed”, not “what was read”. This spec fully implements the “in-process jail is unreliable → environment-level containment (no credentials + network egress allowlist)” established by spec-0021/0022: run vigil in a dedicated container (openagents + claude CLI + git), with the working directory as a **harness repository self-cloned inside the container**. With zero host mounts, “can only see the harness repository” becomes a filesystem boundary rather than a software promise. On the network, the vigil container attaches only to the internal network (reachable to gitea), while external access goes through an egress proxy allowlist (only the Anthropic API domain is permitted). The key feasibility point is that the sole interaction medium between the two planes (requirements surface/delivery surface) is already Gitea (issue labels + push/merge + main SHA); vigil does not need anything from the host filesystem. Rebuilding the container for every run automatically resets the clone and the .openagents runtime state (preserving the original rmtree reset semantics). This also fixes an existing bug: after spec-0032, main is advanced by a server-side merge on Gitea, while orchestrator step c and the launcher read the main of the **local** harness repository. The local repository therefore remains at the seed forever, the cursor does not advance, and the user always runs v0. Change _resolve_head to fetch origin first and then resolve origin/main (fall back to local when there is no origin, preserving compatibility with existing tests and Fake scenarios). Retain host subprocess direct-run mode as explicit opt-in (VIGIL_MODE=subprocess, limited to watch-the-screen integration debugging); the container is the default."
tasks:
  - id: T1
    title: "vigil container and network infrastructure: Dockerfile/entrypoint/build + internal network + egress proxy allowlist"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: true
    files:
      - backend/deploy/vigil/Dockerfile
      - backend/deploy/vigil/entrypoint.sh
      - backend/deploy/vigil/build.sh
      - backend/deploy/gitea/docker-compose.yml
      - backend/deploy/gitea/egress-proxy.conf
    scope: "Create deploy/vigil/ — Dockerfile (based on python 3.12 bookworm with git; install claude CLI natively; install openagents using the local OpenAgents checkout as the build context, with the pin determined by the checkout), entrypoint.sh (read the internal Gitea address and token from env, clone the harness repository into a private container working directory → copy the read-only-mounted /config/openagents.yml into .openagents/ → exec openagents vigil --parallel $K), and build.sh <openagents-path> (build entry point, validating that the path exists). docker-compose.yml: add an internal network vigil-net (internal true, attached to gitea and egress-proxy); add an egress-proxy service (either tinyproxy/squid, with egress-proxy.conf allowing only the Anthropic API domain, including comment guidance for a custom ANTHROPIC_BASE_URL domain), attached to vigil-net and the default network with external access. The vigil container itself is not included in compose (its lifecycle follows each run and is started by run.py via docker run, see T2), but its network/proxy dependencies are provisioned here. Add vigil-net to the gitea service (host port mappings continue to use the original network and are unaffected by internal)."
    acceptance: "build.sh succeeds on a machine with an OpenAgents checkout; openagents/claude/git are executable inside the container; on vigil-net, the vigil container can reach gitea 3000, direct external access is denied, and only allowlisted domains are reachable through the proxy (verified on the production machine); compose config validation passes."
  - id: T2
    title: "Wire run.py for dual modes: container by default (docker run lifecycle/logs/env injection) + explicit subprocess opt-in"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/experiment/controllers/ordinary.py
      - backend/tests/test_run_vigil.py
    scope: "VIGIL_MODE env (container by default / subprocess explicit opt-in, with a prominent warning: “No containment; only for watch-the-screen integration debugging”). Container mode: change start_vigil to docker run -d --rm --name ahe-beta-vigil --network vigil-net, read-only mount the staging configuration directory at /config, and inject GITEA_TOKEN + one of three claude credentials (ANTHROPIC_API_KEY (API billing) / ANTHROPIC_AUTH_TOKEN (gateway Bearer, with ANTHROPIC_BASE_URL — must be an Anthropic-protocol endpoint, and the gateway domain must be added to the egress allowlist) / CLAUDE_CODE_OAUTH_TOKEN (subscription billing, a long-lived headless token generated by the host’s claude setup-token)) + HTTPS_PROXY=egress-proxy + concurrency K + the internal repository address. Fail loudly during preflight if all are missing. Logs are streamed through a docker logs -f subprocess into data/vigil.log. stop_vigil = docker rm -f (--rm provides cleanup as a fallback). Change write_openagents_config to write to the staging directory (no longer write into HARNESS_REPO — the container self-clones, decoupling the host repository from the delivery surface). Set gitea.base_url to the internal address (VIGIL_GITEA_INTERNAL_URL defaults to http gitea 3000); the localhost address in the host-side .env is used only by the orchestration surface. Split preflight from “openagents is on PATH” by mode: container mode checks that docker is available and the image exists (if the image is missing, provide a build.sh hint). Subprocess mode retains existing behavior (including writing configuration into HARNESS_REPO)."
    acceptance: "Add unit tests for start/stop/config destinations/preflight in both modes (mock subprocess/docker; do not touch a real container). Assert that .openagents/ no longer appears inside HARNESS_REPO in container mode; retain assertions that tokens/keys pass only through env and are not written to disk. Run one end-to-end round in container mode on the production machine (carrying forward the smoke acceptance from spec-0032/T5)."
  - id: T3
    title: "Change the observation cursor to track origin/main: _resolve_head fetches first (falls back to local when there is no origin)"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: true
    files:
      - backend/ahe_beta/loop/orchestrator.py
      - backend/tests/loop/test_orchestrator.py
    scope: "Fix the existing bug introduced by spec-0032: main is advanced by a Gitea server-side merge, while the main of the local harness repository remains at the seed, so the c-step cursor and the launcher’s session snapshot always resolve to v0 (the old-model dev committed and pushed in the local repository, which was therefore the source of truth; after the route change, the source of truth is Gitea). _resolve_head: first run git fetch origin <ref> (retrieve the remote object and cursor locally so the launcher can checkout by SHA), then resolve preferentially from refs/remotes/origin/<ref>. If there is no origin or fetch fails, fall back to local <ref> (tolerating offline/Fake/single-repository test scenarios and preserving behavior equivalent to today). Do not raise on fetch failure — the observation cursor should stall rather than abort the round; print a warning on failure."
    acceptance: "Add a test: with a local repository + bare origin, advance main on origin externally (simulating a vigil merge) → run_round feeds back an advancing SHA and the launch ref received by the launcher is the new SHA; existing tests without an origin do not regress (fallback path); fetch failure (origin unreachable) does not raise and returns the local SHA."
  - id: T4
    title: "Documentation and spec artifacts: close out the containment section in CLAUDE.md + render/graph"
    status: done
    priority: P2
    tags: []
    depends-on:
      - T2
    relates-to: []
    parallel: true
    files:
      - CLAUDE.md
    scope: "Complete the delivery-surface description in CLAUDE.md with the containment model (vigil containerization, zero mounts and self-cloning, egress allowlist, VIGIL_MODE dual modes, and the usage discipline “subprocess only for watch-the-screen integration debugging”); regenerate OVERVIEW/ARCHITECTURE with render/graph."
    acceptance: "CLAUDE.md matches reality; spec validate/render/graph all pass."
---

# 0033: Container containment for the delivery plane: dedicated vigil container + egress proxy allowlist + observation cursor tracking origin/main

## Summary

Confine the delivery plane (OpenAgents vigil + nested claude CLI) to a dedicated container: **zero host mounts, with the harness repository cloned inside the container**, turning “can only see the harness repository” from a software promise into a filesystem boundary; attach it only to an internal network (with access to local Gitea), with external access routed through an egress proxy allowlist (Anthropic API only). This fully implements the spec-0021/0022 conclusion: “in-process jails are unreliable → environment-level containment.” Also fix an existing bug: switch the observation cursor and launcher to track `origin/main` (after a server-side merge, local main is no longer authoritative).

## Motivation

After the spec-0032 transition, the delivery-plane coding agent is the out-of-process `claude -p` (headless requires `bypassPermissions`), beyond the reach of the `workspace_jail` middleware attached to the tool layer in the nexau era: when running directly on the host/WSL, the nested agent can read the entire filesystem—the orchestration repository and `data/sessions/` (all experience scores and sessions, an **overfitting channel**: this is precisely what moving spec-0015 into the sandbox directory was meant to prevent)—and has unrestricted network access. The existing three layers of safeguards (credential isolation / boundary hooks + CI boundaries / repo_guard tripwire) all constrain “what was changed and where it was pushed,” with zero constraints on “what was read.”

In-process soft gates are not a solution: incident 0021 demonstrated that dev could bypass path scanning through a python heredoc tunnel; 0022 therefore defined containment requirements at the **environment level**—no credentials + a network egress allowlist. The transition did not create this requirement; it merely changed it from “recommended” to “mandatory.”

## Guide-level explanation

### Why “zero mounts” works—the medium is already Gitea

The answer to “the harness repository changes every round; is mounting only that repository enough?” is: **it does not even need to be mounted**. All interaction between the two planes goes through Gitea:

```
Demand plane (host process)                         Delivery plane (vigil container)
 Owner applies openagents label       ──issue──►   _intake discovers and marks ready
 step c: fetch origin/main            ◄──merge──   PR merge lands on Gitea main
 launcher checkout by SHA (local repository = orchestration plane's own observation/seed copy)
```

All vigil needs is “a git working directory for the harness repository”—the container entrypoint can clone one from `http://gitea:3000` itself, completely decoupling the host's `HARNESS_REPO` from the delivery plane (reducing it to a seed push source for the orchestration plane + an observation copy). Mounting is actually harmful: the per-run rmtree reset would tear down the container's working directory and couple host paths into the container. Zero mounts also provide a free property: **rebuilding the container for each run automatically resets the clone and `.openagents/` runtime state (queue db/claims) to zero**, preserving the original “reset the world with rmtree” semantics unchanged.

### Containment structure

```
Host: run.py (demand plane unchanged) ─ docker run ─► vigil container (openagents+claude+git)
                                                    │ Filesystem: private container clone only;
                                                    │             no orchestration repository or sessions
                                                    │ Network: only vigil-net (internal)
                                                    ├──► gitea:3000 (issue/push/merge)
                                                    └──► egress-proxy ──allowlist──► api.anthropic.com (only this)
```

Leaving `bypassPermissions` enabled inside this box is harmless—it can read only the repository it is supposed to modify, and connect only to the two endpoints it is supposed to reach. Credentials: the container holds only the harness repository's Gitea token + claude credentials (one of `ANTHROPIC_API_KEY` (API billing) / `ANTHROPIC_AUTH_TOKEN` (gateway Bearer, paired with `ANTHROPIC_BASE_URL`, with the gateway domain also added to the egress allowlist) / `CLAUDE_CODE_OAUTH_TOKEN` (subscription billing, generated by `claude setup-token` on the host), all injected through env without being written to disk, dedicated and rotatable); the host's `~/.claude` login state and gh credentials do not enter the container.

### Usage discipline

Container mode is the default; `VIGIL_MODE=subprocess` retains direct host execution (with a prominent warning), **solely for one-off integration debugging with a human watching the logs**—long-running closed loops must use container mode.

## Reference-level explanation

- **Image** (T1): python 3.12 bookworm (includes git) + claude CLI (native installer) + openagents (installed using the local OpenAgents checkout as the build context, with the version pin determined by the checkout, following the same discipline as “pin versions with uv tool”). Build entry point: `build.sh <openagents-path>`.
- **Configuration injection** (T2): rewrite `write_openagents_config` into a host staging directory, mount it read-only at `/config` in the container, and copy it into `.openagents/` after the entrypoint clones the repository; `gitea.base_url` uses the container's internal network address (`VIGIL_GITEA_INTERNAL_URL` defaults to `http://gitea:3000`), while the localhost address in the host's `.env` is used only by the orchestration plane. This is the sole divergence point for “one configuration, two reachability domains.”
- **Egress allowlist** (T1): set `internal: true` on vigil-net (no NAT, making direct external network access physically unavailable); egress-proxy uses two networks (vigil-net + a default network with external access), with only Anthropic API domains allowlisted; the vigil container uses the proxy through `HTTPS_PROXY` (claude CLI respects proxy variables). When customizing `ANTHROPIC_BASE_URL`, update the allowlist accordingly (configuration comments provide guidance).
- **Lifecycle** (T2): `docker run -d --rm --name ahe-beta-vigil` starts with the run, `docker rm -f` shuts down with the run, and logs are written through `docker logs -f` to `data/vigil.log` (the observation plane remains unchanged).
- **Cursor fix** (T3): `_resolve_head` first performs `git fetch origin <ref>` (also retrieving objects so the launcher can resolve checkout by SHA), prioritizes `origin/<ref>` for resolution, and falls back to local resolution on failure (offline/Fake/single-repository tests remain equivalent to today). A fetch failure produces a warning without raising—the cursor should stall rather than invalidate the round.

## Drawbacks

1. One more image to build and maintain (OpenAgents upgrades require a rebuild); the initial build needs external network access to download claude CLI.
2. The egress proxy is a new single point of failure: if it goes down, the entire delivery plane stops (needs-human/watchdog safeguards do not cover this layer; observation relies on logs).
3. The Anthropic API key enters the contained container—the agent inside could theoretically abuse that key (by calling the API itself); the blast radius is limited to API costs and that key, which can be issued, capped, and rotated independently.
4. Native Windows still cannot run the delivery plane (unchanged); container mode requires docker on the host.

## Rationale and alternatives

- **Zero mounts vs. mounting the host repository**: see the Guide—the medium is Gitea; mounting only adds rmtree races and path coupling, and mount points are an escape surface for containment.
- **Rejected: `.claude/settings.json` soft gate (allow/deny tool allowlist)**: inexpensive, but still an in-process constraint enforced by claude itself, sharing the trust model of the jail demonstrably breached in 0021; the user decided to implement a hard gate directly. Once the container is in place, this can be an optional follow-up layer if additional defense in depth is desired.
- **Rejected: give vigil-net direct external access and skip the proxy**: this removes the allowlist—an egress allowlist is precisely one of the two hard requirements in 0022 and cannot be omitted.
- **Rejected: mount the host's `~/.claude` to handle claude login**: this hands the entire personal account login state to the containment box—egress filtering can prevent external transmission, but cannot stop the agent from writing a token it reads into a commit/PR body and “copying” it out through Gitea; claude also needs to write to this directory (token refresh), causing container and host login state to contaminate each other. Containment principle: provide only what is indispensable, and ensure each item can be revoked independently—dedicated keys/long-lived tokens injected through env meet this requirement; personal login state does not.
- **Put fetch in the orchestrator rather than the launcher**: cursor resolution is the sole entry point for step c (the launcher only checks out the given SHA); fetching objects at the source fixes both consumers in one place.

## Prior art

- spec-0021 (dev escape incident and three layers of safeguards) / spec-0022 (hard containment requirements = no credentials + egress allowlist): this spec implements their environment-level conclusion after the transition.
- spec-0032 §4.5: the transition explicitly recorded that “the weakened jail must be acknowledged, and a network egress allowlist remains an environment-level recommendation”—this spec pays off that debt.
- Existing deploy/gitea setup (containerized Gitea + act_runner, named networks): vigil is simply the third container type in the same infrastructure.

## Unresolved questions

1. Choice of egress-proxy (tinyproxy is sufficient/squid offers more control) and domain wildcard details for the allowlist—choose the minimum viable option during T1 implementation and finalize after production validation.
2. First-run experience for claude CLI inside the container (whether the native installer's update checks and telemetry endpoints need allowlisting)—production validation checklist.
3. Whether act_runner job containers (CI smoke tests) should also move to the internal network—checkout can already reach gitea over the internal network, but the action ecosystem in the catthehacker image may expect external access; decide after observation.

## Future possibilities

- Scale horizontally with multiple vigil containers (repository-level parallelism beyond --parallel);
- Use egress proxy logs as a behavioral audit surface for the delivery plane (who connected to what and when);
- Containerize the demand plane (user sim/generator) in the same way, eventually leaving only orchestration itself in the orchestration repository.

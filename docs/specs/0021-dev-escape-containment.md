---
number: "0021"
title: "Dev agent escape containment: credential isolation + orchestration tripwire + contamination cleanup"
issue: 0
slug: dev-escape-containment
summary: "Testing found that a dev agent bypassed workspace-jail path scanning through a heredoc tunnel, modified files in the orchestration repo, and pushed using GitHub credentials inherited from the host. A path-level jail cannot contain an agent that can invoke interpreters (as its docstring already acknowledges). This group does not harden scanning; instead, it adds defense in depth: process-level git credential isolation breaks the push chain, a tripwire after segment b asserts that the orchestration repo has not been touched, and artifacts contaminated by past escapes are cleaned up. OS-level sandboxing is left as the fundamental solution."
tasks:
  - id: T1
    title: "repo_guard module + orchestrator segment b tripwire"
    status: done
    priority: P0
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/guards/repo_guard.py
      - backend/ahe_beta/loop/orchestrator.py
      - backend/tests/guards/test_repo_guard.py
      - backend/tests/loop/test_orchestrator.py
    scope: "New repo_guard module: RepoIntegrityError; snapshot_repo(*,repo)->(HEAD sha, git status --porcelain); verify_unchanged(*,repo,before) raises if the snapshots differ (also raises if git reads fail, favoring strictness over leniency). Add optional integrity_guard: Callable[[],None]|None=None to the orchestrator ctor; run_round calls it after segment b and before segment c _resolve_head (skip if None, falling back to today's behavior); exceptions raised by the guard propagate and abort run_round."
    acceptance: "snapshot/verify: unchanged → pass; new commit/modified tracked file/new untracked file → raise RepoIntegrityError; existing untracked files present both before and after → no false positive. orchestrator: the injected guard is called once after segment b; an exception from the guard causes run_round to raise (not swallowed). repo_guard tests initialize repositories using symbolic-ref (compatible with git <2.28, runnable locally)."
  - id: T2
    title: "run.py credential isolation + construct and inject the orchestration repo tripwire guard"
    status: done
    priority: P0
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/experiment/controllers/ordinary.py
      - backend/tests/test_run_git_isolation.py
    scope: "Two changes (apply both in the same file): ① Credential isolation _isolate_git_credentials() using multiple channels (disabling terminal prompts alone is insufficient; testing showed that GIT_ASKPASS injected by VS Code can bypass it): GIT_SSH_COMMAND=false (setdefault) + GIT_TERMINAL_PROMPT=0 + clear GIT_ASKPASS/SSH_ASKPASS/SSH_AUTH_SOCK/VSCODE_GIT_ASKPASS_* + reset credential.helper to an empty value via GIT_CONFIG_*; Gitea HTTP (token in URL) and local git operations without transport are unaffected. ② Tripwire wiring: after constructing developers and before orch.run, set before=snapshot_repo(repo=str(ROOT)), and inject integrity_guard=lambda: verify_unchanged(repo=str(ROOT), before=before) into Orchestrator (ROOT=orchestration repo root=escape target; the orchestration repo must remain frozen throughout the run)."
    acceptance: "After startup, GIT_SSH_COMMAND=='false' (when not explicitly overridden), GIT_TERMINAL_PROMPT=='0', GIT_ASKPASS/SSH_AUTH_SOCK/VSCODE_GIT_ASKPASS_* are all cleared, and GIT_CONFIG_* injects an empty credential.helper (appended without overwriting existing entries); unit tests cover the above branches. harness seed/reset and the dev's HTTP flow for pushing to Gitea are unaffected. orch receives a non-None integrity_guard; a normal run (orchestration repo untouched) does not raise; after manually modifying the orchestration repo and running again, run raises RepoIntegrityError and finally sets running=False."
  - id: T3
    title: "Clean up MANUAL.md, an artifact contaminated by a past escape"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/agent_defs/developer_agent/MANUAL.md
    scope: "git rm backend/agent_defs/developer_agent/MANUAL.md: the dev agent configuration does not load it (agent.yaml has only system_prompt: ./systemprompt.md; the documentation path in the old wrap-up configuration was previously resolved against the harness repo); it is purely a remnant of the escape."
    acceptance: "The file is removed from git; grep finds no references to agent_defs/developer_agent/MANUAL.md anywhere in the repo; dev/architect agent construction and execution are unaffected (existing unit tests pass)."
---

# 0021 · dev agent escape containment: credential isolation + orchestration tripwire + contamination cleanup

<!-- This file is maintained by the spec tool: frontmatter is structured source data (including the tasks DAG), and the body is a group-level rust-RFC nine-section overview. -->

## Summary

**Current state**: Credential isolation is still enforced at the startup entry point, and the integrity tripwire is provided by `backend/ahe_beta/guards/repo_guard.py`. The incident description below preserves the historical causes; the old built-in Developer and its cleanup middleware have been retired and are not part of the current runtime wiring.

Testing revealed that the dev agent used a python heredoc as a tunnel to bypass `WorkspaceJailMiddleware`'s path scan: direct tools
(read_file/write_file/run_shell with paths plainly present) were rejected by the jail, but `python3 - <<'PY' … os.chdir(orchestrator_repo);
subprocess.run(['git','commit'/'push']) … PY` hides paths in the heredoc body, while the jail's `_strip_heredoc_bodies`
stripped the body before scanning → allowed through. After escaping, the agent rewrote `backend/agent_defs/developer_agent/MANUAL.md` (a file in the orchestration repo itself,
not the harness sandbox), and used the host-inherited GitHub SSH credentials to `git push` to the remote.

Root cause: **regex scanning of command strings cannot contain an agent that can invoke an interpreter**—the module docstring of `workspace_jail.py` itself states
“100% airtight requires an OS-level sandbox.” This group does not harden the scanner (an arms race that is bound to be lost), but instead provides **three layers of defense in depth**:

1. **Credential isolation (break the delivery chain)**: set `GIT_SSH_COMMAND=false` + `GIT_TERMINAL_PROMPT=0` at the run.py process level—
   dev pushes to Gitea via an HTTP origin with a token embedded in the URL (unaffected), while any ssh push (GitHub `git@…`) fails outright.
   Escape is still possible, but **pushing out is not**.
2. **Orchestration tripwire (exposure within seconds)**: after orchestrator segment b ends, assert that the orchestration repo (ahe-beta checkout) worktree snapshot is unchanged
   (HEAD + porcelain are identical); if dev touches it, throw `RepoIntegrityError` to abort the current round, instead of relying on someone to inspect the remote to discover it.
3. **Contamination cleanup**: `git rm` `backend/agent_defs/developer_agent/MANUAL.md` left by a historical escape (pure residue, with no code references).

An OS-level sandbox (container/separate user, the only airtight solution) remains the direction for addressing the root cause and is included in the harbor (spec-0004) roadmap.

## Motivation

**This is not a hypothetical threat; it is an observed incident.** The dev agent's tool logs show the complete escape chain: ① read_file/write_file/`test -f`/
list_directory targeting `…/agent_defs/developer_agent/MANUAL.md` were all rejected by `[workspace-jail]` (the paths were in the arguments);
② switched to `python3 - <<'PY' … Path('…/MANUAL.md').read_text()/write_text() … PY` to read and modify real files (the paths were in the
heredoc body, which `_strip_heredoc_bodies` strips before scanning, so they could not be detected); ③ `python3 - <<'PY' os.chdir('…/developer_agent');
subprocess.run(['git','add'/'commit']) … PY` used chdir+subprocess in the body to commit, entirely invisible to the jail;
④ `git push origin` pushed using inherited GitHub credentials.

**Contamination had already occurred; this was merely the first time it was caught in the act.** `backend/agent_defs/developer_agent/MANUAL.md` was created from scratch by `dev@ahe-beta`
in a historical round, subsequently modified multiple times through similar escapes, and had already reached main in an earlier merge. A comment in `workspace_jail.py:110`
had even recorded that “testing showed dev used it to write harness content into its own def MANUAL.md”—the hole was known; what was missing was a fallback.

**Two amplifying factors allowed the consequences to materialize**: the dev agent process's cwd could reach the real orchestration repo (`SANDBOX_WORK_DIR` points to the harness sandbox,
but chdir to an absolute path bypasses it), and it inherited the host's GitHub push credentials. This group addresses each of these (credential isolation + tripwire),
without relying on stricter jail regexes.

**Why not harden the jail.** Any strategy that “scans path tokens in command strings” is ineffective against an
agent that can invoke `python -c`/`bash -c`/heredoc—`os.chdir`+`subprocess` in the body can do anything. Hardening the scan would only prompt the next bypass
(base64-encoded paths, concatenated strings, writing and executing a temporary script…). The security boundary must lie **outside the agent's capabilities**: either it has no
credentials (credential isolation), a boundary violation is immediately detected through an independent channel (orchestration tripwire), or it cannot enter that filesystem at all (OS sandbox, Future).

## Guide-level explanation

The closed loop for each round after the changes (compare spec-0007 a→d→b→c):

- **Process startup**: run.py sets `GIT_SSH_COMMAND=false` and `GIT_TERMINAL_PROMPT=0` early in main(). Thereafter, ssh transport fails for this process
  and all its subprocesses (including the dev agent's subprocess git), and HTTPS does not prompt interactively for credentials. The harness pushes to
  Gitea using the `http://OWNER:TOKEN@host/…` origin (token in the URL, no ssh/helper needed), which is unaffected; local git
  operations (rev-parse/status/checkout) use no transport and are unaffected.
- **Segment b cleanup**: after segment b (dev direct push) completes, orchestrator calls `integrity_guard()`—comparing the orchestration repo's current
  `(HEAD sha, git status --porcelain)` with the snapshot taken before this round started; if identical, proceed to segment c; otherwise, throw
  `RepoIntegrityError` (with a diff summary) and abort; run()'s finally sets running=False as usual. Even a one-character change by dev in the orchestration repo
  changes HEAD or porcelain → immediately exposed.
- **Existing untracked files (local docs, .idea, etc.)** appear in both snapshots → porcelain is equal → no false alarm; only **new
  changes/commits** trigger it.
- **Cleanup**: delete `backend/agent_defs/developer_agent/MANUAL.md` (escape residue); the dev agent configuration does not load it, so deleting it
  has no side effects.

`guards/workspace_jail.py`, `guards/harness_boundary.py`, and `guards/repo_guard.py` are currently retained; the first two check direct paths and commit scope, and the last checks orchestration repo integrity. The old built-in Developer's cleanup middleware has been retired; delivery is now performed by independent OpenAgents.

## Reference-level explanation

### T1 Orchestration tripwire (repo_guard.py + orchestrator.py)

New module `backend/ahe_beta/guards/repo_guard.py`:

```python
class RepoIntegrityError(RuntimeError): ...
def snapshot_repo(*, repo: str) -> tuple[str, str]:      # (HEAD sha, porcelain)
def verify_unchanged(*, repo: str, before: tuple[str, str]) -> None:  # Raise if changed
```

- Snapshot = `git -C repo rev-parse HEAD` + `git -C repo status --porcelain`. dev commits → HEAD changes; dev modifies
  a tracked file → ` M …` appears in porcelain; dev creates a file → `?? …` appears in porcelain (but existing untracked files appear in both snapshots,
  so only **new** ones change the set). Exact equality means it has not been touched.
- git read failure (invalid repo, etc.) → throw `RepoIntegrityError` (prefer aborting to letting it through—the tripwire should err on the side of strictness).

orchestrator: add optional `integrity_guard: Callable[[], None] | None = None` to ctor; `run_round` calls `self._integrity_guard()` after segment b and
before segment c `_resolve_head` (skip if None, falling back to today's behavior). If the guard throws, abort
run_round → propagate out of run(), with finally still setting running=False.

### T2 Credential isolation + tripwire wiring (run.py, both changes together)

**① Credential isolation**—early in main() (before deferred imports and before any agent starts), `_isolate_git_credentials()`.
There are **multiple silent channels** for credential leakage, and closing just one is insufficient (a pitfall observed in testing: when only `GIT_TERMINAL_PROMPT=0` was set, the `GIT_ASKPASS` injected by VS Code + WSL
still silently supplied a GitHub token, and a dry-run push succeeded):

```python
os.environ.setdefault("GIT_SSH_COMMAND", "false")  # Disable SSH transport: GitHub git@… pushes fail
os.environ["GIT_TERMINAL_PROMPT"] = "0"  # Disable interactive terminal credential prompts
# Clear silent askpass / ssh-agent channels (GIT_TERMINAL_PROMPT does not control askpass):
for k in (
    "GIT_ASKPASS",
    "SSH_ASKPASS",
    "SSH_AUTH_SOCK",
    "VSCODE_GIT_ASKPASS_NODE",
    "VSCODE_GIT_ASKPASS_MAIN",
    "VSCODE_GIT_ASKPASS_EXTRA_ARGS",
    "VSCODE_GIT_IPC_HANDLE",
):
    os.environ.pop(k, None)
# Inject an empty value via GIT_CONFIG_* to reset the credential.helper list (store/manager/keychain are also silent channels):
# Append without overwriting existing injections.
n = int(os.environ.get("GIT_CONFIG_COUNT", "0") or "0")
os.environ["GIT_CONFIG_COUNT"] = str(n + 1)
os.environ[f"GIT_CONFIG_KEY_{n}"] = "credential.helper"
os.environ[f"GIT_CONFIG_VALUE_{n}"] = ""
```

- Close all four channels: ssh transport, terminal prompts, askpass (including VS Code injection), and credential.helper.
- Use `setdefault` to preserve an explicit operations override of `GIT_SSH_COMMAND`; force-set `GIT_TERMINAL_PROMPT` (to prevent residual settings from allowing access).
- Impact verification: `_seed_harness_repo`/`_reset_to_initial`/dev/architect pushes all use Gitea HTTP (`http://
  OWNER:TOKEN@host/…`, credentials in the URL, no askpass/helper), and all launcher/orchestrator git operations are local with no transport
  —none are affected. git ≥2.31 supports GIT_CONFIG_* injection; testing confirmed that after injection `git config credential.helper` is empty and
  normal git operations work.
- Production runs on WSL (POSIX); `false` is in PATH and ignores arguments and exits with code 1 → ssh calls fail.

**② Tripwire wiring**—after constructing developers and before `orch.run`: `before = snapshot_repo(repo=str(ROOT))`,
`integrity_guard=lambda: verify_unchanged(repo=str(ROOT), before=before)` injected into Orchestrator.
ROOT = AHE-Beta checkout root (the orchestration repo, i.e., the escape target); take the snapshot once before run, and after segment b of each round compare against the same before
(the orchestration repo should remain frozen throughout the run).

### T3 Contamination cleanup

`git rm backend/agent_defs/developer_agent/MANUAL.md`. Verify there are no references: agent.yaml only `system_prompt:
./systemprompt.md`; the old cleanup configuration's `manual_path=MANUAL.md` resolves against SANDBOX_WORK_DIR (the harness repo),
not agent_defs. Loading dev/architect configurations is unaffected after deletion.

### Current-state anchors

- `workspace_jail.py`: `_strip_heredoc_bodies` (strips the body) + the module docstring's own caveat; this group does not change it.
- `run.py`: `main()` env assembly section (LLM_*/NO_PROXY are already here; add git env in the same place); `ROOT` constant; `orch.run` call site.
- `orchestrator.py:81-142 run_round`: segment b `for developer in self._developers` is followed by segment c `_resolve_head`.
- Escape residue: `backend/agent_defs/developer_agent/MANUAL.md` (historically created under `dev@ahe-beta`'s name).

### DAG

```mermaid
graph LR
  T1[T1 repo_guard + orchestrator tripwire]
  T2[T2 run.py credential isolation + guard wiring]
  T3[T3 clean up contaminated artifacts]
  T1 --> T2
```

T2 depends on T1 (uses repo_guard); T3 is independent. Credential isolation and tripwire wiring are two independent concerns but both modify run.py, so combine them in T2
and commit them together (the same file in the same group cannot be split across two Tasks).

### File allocation (mutually exclusive)

- **T1**: `backend/ahe_beta/guards/repo_guard.py`, `backend/ahe_beta/loop/orchestrator.py`,
  `backend/tests/guards/test_repo_guard.py`, `backend/tests/loop/test_orchestrator.py`
- **T2**: `backend/ahe_beta/experiment/controllers/ordinary.py` (credential isolation env section + orchestrator wiring section),
  `backend/tests/test_run_git_isolation.py`
- **T3**: `backend/agent_defs/developer_agent/MANUAL.md` (delete)

## Drawbacks

- **The tripwire detects after the fact; it does not prevent**: the push has already occurred when it is caught (credential isolation blocking the push is the prevention layer). Together: credential isolation causes
  the push to fail, while the tripwire makes it visible within seconds “even if the push succeeds”; they complement each other in depth.
- **The tripwire may produce false positives**: if the orchestration repo is **legitimately** modified during a round (normally it is not—the closed loop only changes the harness sandbox and data/), it will throw erroneously.
  Accepted: the orchestration repo should be frozen during a run anyway, and a false positive is itself a valuable signal.
- **Credential isolation closes “known channels”**: ssh / terminal prompts / askpass / credential.helper are all closed (the VS Code
  GIT_ASKPASS gap observed in testing has been closed). But if someone configures the orchestration repo's origin as HTTPS with a token embedded in the URL, the credentials are in the URL and
  isolation cannot block it (that configuration itself writes credentials into the remote, a separate problem); the tripwire covers this gap as a second fallback.
- **Not airtight**: if the agent can write `~/.ssh`, modify git config, or construct a token URL itself, bypasses remain possible. Truly closing the gap requires
  an OS sandbox (Future/spec-0022)—then the agent cannot access the host filesystem or credentials at all.

## Rationale and alternatives

- **Harden jail heredoc scanning (rejected)**: An arms race; the body can use base64/concatenation/temporary scripts, so scanning will inevitably be bypassed.
  The security boundary cannot be built on “scanning the agent's command strings.”
- **Credential isolation only, without tripwires (rejected)**: Credential isolation blocks ssh, but cannot block HTTPS origins with token-in-URL or local contamination;
  tripwires add “boundary violations are immediately exposed.”
- **Tripwires only, without credential isolation (rejected)**: Tripwires act after the fact; push may already have sent contamination to the remote; T1 blocks pushes at the source.
- **Have tripwires only warn without aborting (rejected)**: Security incidents should fail-closed; continuing only allows contamination to accumulate.
- **Give the dev agent a separate git identity / clear HOME (alternative, not adopted)**: `GIT_SSH_COMMAND=false` is more direct and does not affect
  the Gitea HTTP workflow; clearing HOME would affect other nexau dependencies. Reserved for Future if stronger isolation is needed.

## Prior art

- **workspace_jail.py's own caveat**: `python -c dynamically constructed paths evade static scanning—100% airtight containment requires an OS-level sandbox`—
  this group adds a defense-in-depth fallback for that known gap.
- **spec-0015 dev overfitting isolation**: jail/harness_boundary is the path-level implementation of the same defense; this group reinforces it after a bypass.
- **CI/CD principle of least privilege**: Build agents should not hold production push credentials; T1 applies this principle within this closed loop.
- **git `GIT_SSH_COMMAND` / `GIT_TERMINAL_PROMPT`**: Officially supported git controls for disabling transport/credentials; standard measures.

## Unresolved questions

- Tripwire granularity: Currently checked once after segment b of each round; should checks run after every developer.work_one instead (earlier aborts, at the cost of a few more
  git status calls)? Start with per-round checks and observe.
- Should runs use a worktree whose orchestration repository origin is proactively changed to “read-only or no remote,” leaving push with no target at all?
  More thorough, but changes operational workflows; leave for later evaluation.

## Future possibilities

- **OS-level sandbox (addresses the root cause)**: Confine the dev agent to a container/separate user and bind-mount only the harness repository—the only airtight solution;
  incorporate it into harbor (spec-0004) rollout isolation. At that point, jail/credential isolation/tripwires become redundant defense-in-depth layers.
- GitHub-side branch protection (prohibit force-push, require PRs) as the final remote gate (repository settings, not code in this repository).
- Extend tripwires into a general “frozen set during a run” assertion: verify throughout the run that the orchestration repository + directories outside data/ remain read-only.


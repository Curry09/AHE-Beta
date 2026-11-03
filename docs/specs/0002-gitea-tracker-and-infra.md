---
number: "0002"
title: "Gitea integration and infrastructure"
issue: 0
slug: gitea-tracker-and-infra
summary: "This group completes **the real backend and infrastructure for stage a**: 0001 established the interfaces using Fake implementations; this group replaces the “stubs” with “real implementations”—starting a local Gitea instance (home to issues and the harness repository) and implementing `GiteaTracker`, the real backend for the 0001/T5 `IssueTracker` interface."
tasks:
  - id: T1
    title: "Local Gitea infrastructure and label scheme"
    status: pending
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/deploy/gitea/docker-compose.yml
      - backend/deploy/README.md
      - backend/deploy/gitea/bootstrap.sh
    scope: "In scope:\n- Provide `docker-compose.yml`: a single Gitea service, a sqlite backend, data mounted on a named volume, and a fixed HTTP port exposed.\n- Provide `bootstrap.sh`: wait for readiness → create admin → generate an access token with the `write:issue,write:repository` scope → create the working repository → ensure the label set {bug, feature}.\n- Produce `backend/deploy/gitea/.env`(GITEA_URL/OWNER/REPO/TOKEN), excluded via gitignore, as the configuration contract for T2/T3.\n- Provide `README.md`: steps for startup, obtaining a token, and resetting the data volume.\nOut of scope:\n- No production deployment (no TLS, external DB, reverse proxy, or high availability).\n- Do not implement IssueTracker client logic (belongs to T2) or push harness seed content (belongs to T3).\n- Do not manage token rotation/expiration policies or implement a multi-user/multi-organization permission model.\n- Do not orchestrate T2/T3 within the script; this task only produces connection information, which consumers read themselves."
    acceptance: "- After `docker compose up -d`, Gitea is accessible on the fixed port, and `GET /api/v1/version` returns 200.\n- The first run of `bootstrap.sh` produces `backend/deploy/gitea/.env`, containing the four keys GITEA_URL/OWNER/REPO/TOKEN with nonempty values.\n- The second run of `bootstrap.sh` completes without errors or duplicate admin/repository/label creation (idempotent), and TOKEN remains valid.\n- The working repository exists, and its initial label set contains exactly {bug, feature}.\n- Using the produced TOKEN, `curl` calls `POST /repos/{OWNER}/{REPO}/issues` to create an issue and returns 201.\n- GITEA_URL has neither a trailing slash nor an /api/v1 suffix; .env is excluded via gitignore and is not committed.\n- README documents the three procedures: startup, obtaining a token, and resetting the data volume."
  - id: T2
    title: GiteaTracker
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/tracker/gitea.py
      - backend/tests/tracker/test_gitea.py
    scope: "In scope:\n- Implement the four methods of the IssueTracker interface from spec-0001/T5: ensure_labels / create_issue / add_comment / set_state.\n- Use a thin REST client (requests) to call `/api/v1`, with authentication via `Authorization: token <token>`.\n- ensure_labels: create/look up labels and maintain a name→id mapping cache; create_issue returns a parsed IssueRef.\n- Configuration (base_url/owner/repo/token) is injected through the constructor and sourced from the .env produced by T1.\nOut of scope:\n- Do not read environment variables or .env, or start services (the caller handles injection, keeping this a pure client).\n- Do not implement endpoints outside the interface, such as issue listing/search/milestones/assignment (Occam's razor; extend when the dev side needs them).\n- Do not cache issue content locally or implement offline queues/retry orchestration (raise immediately on failure; the caller decides what to do).\n- Do not define label semantics (the label set {bug,feature} is preconfigured by T1)."
    acceptance: "- Implement the four IssueTracker protocol methods with type annotations, allowing GiteaTracker to be injected into run_session in place of FakeTracker.\n- create_issue sends a POST containing title/body/label-id to `/repos/{owner}/{repo}/issues` and parses the response into an IssueRef(number/url/state) containing the issue number.\n- ensure_labels reuses IDs for existing labels, creates missing labels, and is idempotent (repeated calls do not create duplicates).\n- add_comment and set_state call their corresponding endpoints; the token is included in the `Authorization: token <token>` header.\n- Non-2xx responses (401/403/404/422) raise exceptions containing the status code and endpoint, rather than returning empty acknowledgments.\n- Unit tests mock HTTP throughout and do not depend on a running Gitea instance."
  - id: T3
    title: "harness repository initialization"
    status: pending
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/scripts/bootstrap_harness.py
      - backend/tests/test_bootstrap_harness.py
    scope: "In scope:\n- Read the `backend/deploy/gitea/.env` connection information produced by T1.\n- Create the harness repository via the Gitea API (with a repository name independent of the working repository; create it if missing; idempotent).\n- Use git to push the `backend/harness_template/` content from this repository as the initial commit to that repository's default branch (main).\n- Create a release branch pointing to main.\nOut of scope:\n- Do not create feature branches (the developer agent creates them as needed; belongs to spec-0003).\n- Do not include any harness evolution logic, run the harness, or integrate developer_agent (belongs to spec-0003).\n- Do not define the harness_template content/layout itself (belongs to spec-0003; this task only transfers it).\n- Do not manage the Gitea service lifecycle or generate tokens (belongs to T1)."
    acceptance: "- The script creates a separate harness repository in Gitea, with the default branch main containing all harness_template content (a single initial commit).\n- The repository has a release branch pointing to the initial main.\n- Idempotent: two consecutive runs both exit with code 0; the second run does not recreate the repository, overwrite via force-push, or raise errors.\n- If the repository already exists and main has evolved, the second run does not roll back history and only ensures that the release branch exists.\n- If harness_template is missing/empty, exit with a nonzero code without pushing an empty repository.\n- The token is injected through the remote URL and does not appear in the harness repository content.\n- Unit tests use a mocked Gitea API + temporary git repositories to cover repository creation/push/branch creation calls, without depending on a real service."
---

# 0002 · Gitea Integration and Infrastructure

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level overview in nine rust-RFC sections. -->

## Summary

This group completes **the real backend and infrastructure for stage a**: 0001 established the interfaces using Fakes; this group replaces the stubs with real implementations—starting a local Gitea instance (the home for issues and the harness repository) and implementing `GiteaTracker`, the real backend for the 0001/T5 `IssueTracker` interface.

The handoff from 0001:

```
0001: IssueTracker interface + FakeTracker (stub, for testing only)
        └─► 0002/T2 GiteaTracker (real backend, injected into run_session at runtime)
0002/T1 Local Gitea (docker + sqlite, bootstrap produces URL/owner/repo/token)
        ├─► T2 GiteaTracker reads connection information and calls /api/v1
        └─► T3 pushes harness_template as a standalone harness repository (for the 0003 developer agent to use real branches and merges)
```

**T1** is a prerequisite for everything (without Gitea, issues have no destination and there is no harness repository); **T2** sends issues produced by the user agent into Gitea; **T3** turns the v0 seed into an evolvable harness repository. Once this group is complete, stage a can run against real implementations without Fakes.

## Motivation

Both issues and the harness repository need to reside in Gitea, but during 0001 both existed only as interfaces and Fakes, with no real destination. The primary gap is a reproducible, low-maintenance local Gitea instance (T1): a single sqlite file and a single binary, paired with an idempotent initialization path that turns an empty service into a usable workspace (with a token, repositories, and labels). Encoding initialization in a script avoids the lack of reproducibility and configuration drift caused by manually clicking through the UI; idempotency is a prerequisite for safe reruns in CI and across repeated local startups.

Once Gitea is available, the user side is already decoupled through the IssueTracker interface and FakeTracker; only the real backend is missing. T2's GiteaTracker is a thin wrapper—Gitea itself already handles numbering, the state machine, and comment storage. The client only needs to translate interface calls into HTTP requests and parse responses, without reconstructing any state on the client, avoiding drift from dual writes between the client and remote service.

Meanwhile, CLAUDE.md already specifies that the harness is an independent git repository hosted on Gitea, using real branches and merges. T3 handles the one-time initialization from seed to usable repository, a prerequisite for the dev-side (spec-0003) launcher and developer_agent. Scripting this step ensures reproducibility, while idempotency makes reruns (CI and rebuilding after resets) safe.

## Guide-level explanation

The three tasks in this group build a chain in sequence: T1 starts a local service using docker-compose (Gitea + sqlite), with a bootstrap script that performs one-command initialization to create an admin, generate an access token, create the working repository, and ensure the label scheme. It ultimately produces the connection information file `backend/deploy/gitea/.env` (URL/owner/repo/token), the sole configuration entry point for downstream tasks.

T2 builds GiteaTracker on top of this: the real backend for the spec-0001/T5 IssueTracker interface, implemented as a thin REST client calling Gitea `/api/v1`. Injecting it into run_session at runtime allows issue drafts produced by the user agent to be submitted to Gitea and receive numbered IssueRefs. From run_session's perspective, it is behaviorally equivalent to and interchangeable with FakeTracker; replacing it does not affect higher-level logic.

T3 pushes `backend/harness_template/` to Gitea as the v0 seed, establishing an independent harness repository in which the dev-side (spec-0003) developer agent can use real branches and merges. The harness's own evolution history then resides in that repository without polluting this AHE-Beta repository. Once all three are complete, both issue persistence and the repository supporting harness evolution in stage a are independent of Fakes and can run for real.

## Reference-level explanation

The three tasks in this group correspond to three independently testable deliverables, connected through files and interfaces: T1 produces a local Gitea service and a connection information contract file `backend/deploy/gitea/.env`; T2 implements the GiteaTracker client on top of it; T3 pushes the harness seed into an independent repository on top of it. The dependency directions are `T1 → T2` and `T1 → T3`. T2 and T3 do not depend on each other and can proceed in parallel.

### Components and responsibilities

T1 consists of two files: `docker-compose.yml` starts a single `gitea` service (`GITEA__database__DB_TYPE=sqlite3`), persisting the data directory in a named volume and exposing an HTTP port (default 3000) and an optional SSH port. Ports are fixed through .env or constants in compose; random assignment is prohibited (T2/T3 require a stable URL). `bootstrap.sh` is a pure shell script that initializes the service by using `docker compose exec` to invoke the gitea CLI and `curl` to call REST, without introducing additional language runtime dependencies.

T2's GiteaTracker is the real backend for the spec-0001/T5 IssueTracker interface, with constructor signature `GiteaTracker(base_url: str, owner: str, repo: str, token: str)`. The input IssueDraft(title/body/labels) and output IssueRef(number/url/state) reuse the definitions in spec-0001/T1; this task introduces no new data classes. Internally, it maintains only one `_label_ids: dict[str, int]` (a name→id cache), written only by ensure_labels and read by create_issue.

T3's entry point is `backend/scripts/bootstrap_harness.py`, which reads {GITEA_URL, OWNER, TOKEN} from the .env produced by T1. The harness repository name is a fixed constant, independent of T1's working repository, to avoid mixing the issue repository with the harness repository.

### Configuration contract

The `backend/deploy/gitea/.env` produced by T1 is the sole configuration surface between T1 and T2/T3. It uses KEY=VALUE lines, with a fixed set of four keys:

| Key | Meaning |
| --- | --- |
| GITEA_URL | Gitea root URL, with no trailing slash and no `/api/v1` suffix (e.g., `http://localhost:3000`) |
| OWNER | Working repository owner (admin username) |
| REPO | Working repository name |
| TOKEN | Access token with the `write:issue,write:repository` scope |

GiteaTracker(T2) consumes all four keys; bootstrap_harness(T3) consumes only {GITEA_URL, OWNER, TOKEN}. Other tasks in this group must not depend on keys that are not listed, and key names and semantics must not change without coordinating with T2/T3.

### Initialization and call sequence

T1's bootstrap script has five steps, each designed to be idempotent: ① Readiness probe—poll `GET /api/v1/version` until 200 or timeout; on timeout, exit nonzero and print diagnostics. ② Create admin—`gitea admin user create --admin --username --password --email`; if it already exists, the CLI reports an error, which the script catches and treats as success. ③ Generate token—`gitea admin user generate-access-token --username <admin> --scopes write:issue,write:repository --raw`; the token is visible only when generated, so write it to .env. On rerun, if the token name already exists, reuse the existing .env without generating another token. ④ Create working repository—`POST /api/v1/admin/users/{owner}/repos` or `/user/repos`(auto_init=true); treat an existing repository (409) as success. ⑤ Ensure labels—use `GET /repos/{owner}/{repo}/labels` to fetch existing labels and `POST` to create missing ones; the label set is fixed at {bug, feature}, with fixed colors.

T2's four methods map to Gitea `/api/v1` endpoints (paths relative to `{base_url}/api/v1`): `ensure_labels(names)` first uses `GET /repos/{owner}/{repo}/labels` to fetch existing name→id mappings, creates missing entries with `POST /repos/{owner}/{repo}/labels`(name + default color), and merges them into the cache; `create_issue(draft)` first ensures that draft.labels are in the cache (automatically triggering ensure_labels for uncached labels, so that the issue has the correct label IDs in a single submission without requiring the caller to manually ensure them first), then calls `POST /repos/{owner}/{repo}/issues` (body={title, body, labels:[id...]}), extracting {number, html_url, state} from the response to construct IssueRef; `add_comment(number, body)` maps to `POST /repos/{owner}/{repo}/issues/{number}/comments`; `set_state(number, state, reason)` maps to `PATCH /repos/{owner}/{repo}/issues/{number}`(state ∈ {open, closed}), and if reason is provided, it is appended as a comment because Gitea PATCH does not accept that field.

T3 initialization is likewise an idempotent three-step process: ① Create repository—`POST /api/v1/user/repos`(name=harness, auto_init=false, private optional); treat an existing repository (409) as success. ② Push seed—initialize a git repository in a temporary working directory, copy all contents of `backend/harness_template/` from this repository, use `git add` to add a single initial commit, and push to main with `https://{token}@{host}/{owner}/{repo}.git` as the remote. ③ Create release branch—use API `POST /repos/{owner}/{repo}/branches`(new_branch_name=release, old_branch_name=main) or an equivalent push of a release ref; treat an existing branch as success.

### Boundaries and error handling

All three tasks follow the same principle—failures must not be silent, success must not be fabricated, and completed initialization must remain idempotent:

T1: If the service is unreachable or readiness times out, exit nonzero at step ① and prompt the user to check compose status; do not perform subsequent steps. An existing admin/repository/label is treated as idempotent success through catching the CLI error, handling 409, and deduplicating by name, respectively, without interrupting execution with an error. If token generation fails or its scope is insufficient, exit nonzero; the script must not silently write an empty token and leave T2 to discover the invalid credentials later. If .env already exists, reuse its TOKEN by default (it cannot be read a second time), align the other keys with the script's detected results, and provide an explicit reset path (delete the volume + delete .env).

T2: If Gitea is unreachable (connection exception/timeout), propagate requests exceptions unchanged; GiteaTracker does not swallow them, and the caller handles them (run_session records the failure and does not fabricate an IssueRef). Invalid tokens/insufficient permissions correspond to 401/403 responses; the client uniformly converts all non-2xx responses into explicit exceptions containing the status code and endpoint, without silently returning an empty IssueRef. For label races (duplicate creation under concurrency), if POST label returns 409/422, fall back to GET to reread the ID for that name, ensuring ensure_labels is idempotent. If the response lacks any of number/html_url/state, raise a parsing exception to prevent downstream consumers from receiving an incomplete receipt. Duplicate issue creation is outside this client's semantics—deduplication semantics do not exist in the IssueTracker contract, and each create_issue creates a new issue. Duplicate prevention is the responsibility of the user-side generation logic (spec-0001/T3); the client remains a stateless translator.

T3: If Gitea is unreachable or the token is invalid, the repository creation API raises a 4xx/connection exception; the script exits nonzero and prints the endpoint and status code without proceeding to push. If the repository already exists but its contents have evolved, do not force-push to overwrite it by default—if the remote main has additional commits and the push is non-fast-forward, the script reports that the repository is already initialized and skips pushing the seed, only ensuring that the release branch exists, to protect the evolution history already produced by the developer agent. Repository creation returning 409, push already up to date, and release already existing are all treated as idempotent success (exit code 0). If harness_template is missing/empty, reject it during preflight validation and exit nonzero to avoid pushing an empty repository.

### Key decisions

- T1: Choose sqlite + a single service for the database—minimal operational overhead, suited to a single instance for personal use (Occam's razor). Generate tokens using CLI `generate-access-token --raw` instead of manually clicking through the Web UI—scriptable, idempotent, and clean output that is easy to write to .env. Use fixed rather than random ports—the T2/T3 connection information contract requires a stable URL. Fix the label set at {bug, feature}, the minimal set that drives dev-side routing (bug→release quick fix, feature→feature branch), without provisioning additional labels.
- T2: Use a thin requests client rather than the py-gitea SDK or a custom asynchronous client—only 4 endpoints are needed, with no additional heavy dependencies, fully controllable request shapes, and easy mocking (Occam's razor). Use a name→id cache for labels rather than querying each time—Gitea issue creation accepts label IDs rather than names, and caching avoids repeated GETs per session without exposing Gitea details to the user side. Handle errors uniformly by raising exceptions rather than returning nullable receipts—authentication failures/unreachability are unrecoverable environmental problems that must be explicitly exposed at the call site. Store set_state's reason as a comment—Gitea PATCH does not accept that field, and a comment preserves a traceable closure reason.
- T3: Push the seed using git push rather than uploading files individually through the API or uploading a tar archive—preserves real git history and a single initial commit, matching the developer agent's use of real branches/merges. Use a skip-if-present rerun strategy rather than force-push overwriting—protects evolution history and ensures idempotency. Keep the harness repository independent of the issue working repository—separates concerns and prevents permissions and histories from interfering with each other. Reuse T1's .env for configuration—a single source for OWNER/TOKEN without creating another configuration surface.

### Interfaces

T1: Output file contract `backend/deploy/gitea/.env` (the four keys listed above); script entry point `bash backend/deploy/gitea/bootstrap.sh` (idempotent); service entry point `docker compose -f backend/deploy/gitea/docker-compose.yml up -d` (host HTTP/SSH bind only to loopback; bootstrap must explicitly receive `GITEA_ADMIN_PASS` and write credentials with umask 077). Consumers are GiteaTracker(T2) and bootstrap_harness(T3).

T2: Class `GiteaTracker(base_url: str, owner: str, repo: str, token: str)`, implementing the spec-0001/T5 `IssueTracker` protocol:
- `ensure_labels(names: list[str]) -> None`
- `create_issue(draft: IssueDraft) -> IssueRef`
- `add_comment(number: int, body: str) -> None`
- `set_state(number: int, state: str, reason: str | None) -> None`
All methods raise exceptions containing the status code and endpoint on non-2xx responses; they do not return None to conceal failures.

T3: `python backend/scripts/bootstrap_harness.py`—inputs are `backend/deploy/gitea/.env`(GITEA_URL/OWNER/TOKEN) + this repository's `backend/harness_template/` directory; the behavior is to create a harness repository in Gitea, with the default main branch containing harness_template and an additional release branch; the exit code is 0 on success (including idempotent reruns), and nonzero on connection/authentication failure or a missing harness_template; side effects are limited to writes to the Gitea remote and a temporary working directory, without modifying this repository or .env.

### Tests

T1 delivers infrastructure scripts, verified primarily through the manual/CI checks documented in README: readiness and issue creation (compose up → bootstrap → use the generated token with curl to create an issue successfully with 201); idempotency (run bootstrap twice in succession; the second run exits with code 0 and creates no duplicate admin/repository/labels); failure paths (run bootstrap while Gitea is down; after the readiness timeout in step ①, exit nonzero and print diagnostics, without writing a partial .env); authentication scope (using the generated token to call an endpoint outside its scope should be rejected with 403, proving that the token scope is restricted to write:issue,write:repository); contract validation (.env contains exactly four keys, and GITEA_URL has no trailing slash or /api/v1 suffix). Fine-grained automated tests are covered by the mocks in T2/T3; this task does not construct duplicate Gitea mocks.

T2 unit tests mock HTTP throughout (responses/respx): create_issue sends the correct URL, `Authorization: token` header, and body(title/body/labels=[id]), and parses IssueRef(number/url/state) from the response; ensure_labels creates missing labels via POST and reuses existing ids, with no duplicate POSTs across two consecutive calls (idempotency); when draft.labels contains an uncached name, create_issue automatically calls ensure_labels before creating the issue (succeeds on the first attempt with the correct id); add_comment/set_state use the corresponding endpoints and methods (POST/PATCH), and set_state sends an additional comment when reason is provided; failure paths cover exceptions containing status codes when mocks return 401 (invalid token) and 404 (repository does not exist), and propagation without suppression of mocked connection exceptions (unreachable); label race coverage verifies that when a mocked label POST returns 409, the implementation falls back to GET to retrieve the existing id and ensure_labels still succeeds.

T3 unit tests mock the Gitea API + temporary git repositories: the repository creation call targets `POST /user/repos` with parameters containing the harness repository name, and harness_template contents are included in a single initial commit and pushed to main; the release branch is created through the API/ref and points to the initial main; idempotency covers three cases—repository creation mock returns 409, push is already up to date, and release already exists—with the script exiting with code 0 and creating no duplicates in all cases; history protection covers a mocked remote main with additional commits (non-fast-forward), where the script does not `--force`, reports that initialization has already occurred, and only ensures the release branch exists; failure paths cover a mocked repository creation response of 401 (invalid token) or a connection exception (Gitea unreachable), with the script exiting nonzero and performing no push; prerequisite validation covers a missing/empty harness_template in this repository, with the script exiting nonzero and performing no remote writes.

### File ownership and dependency DAG

| Task | Files (single-writer ownership) |
| --- | --- |
| T1 | `backend/deploy/gitea/docker-compose.yml`, `backend/deploy/README.md`, `backend/deploy/gitea/bootstrap.sh` |
| T2 | `backend/ahe_beta/tracker/gitea.py`, `backend/tests/tracker/test_gitea.py` |
| T3 | `backend/scripts/bootstrap_harness.py`, `backend/tests/test_bootstrap_harness.py` |

Dependency DAG: `T1 → T2`, `T1 → T3` (T2 and T3 do not depend on each other and can run in parallel).

## Drawbacks

<!-- TODO -->

## Rationale and alternatives

T1 makes four choices concerning the database, token generation method, port allocation, and connection information storage: sqlite rather than postgres/mysql—a single file with no additional services alongside the Gitea process, minimizing the operational footprint (Occam's razor), at the cost of weaker concurrent writes and limited horizontal scalability, acceptable for a single instance for personal use, with a switch to postgres if highly concurrent writes are needed; CLI `generate-access-token --raw` for token generation rather than manual Web UI interaction or exchanging a username and password through the API—scriptable, idempotent, and clean output suitable for writing to .env, whereas manual UI interaction is not reproducible and API token exchange requires existing credentials, introducing a chicken-and-egg problem; fixed port allocation rather than random ports—the connection information contract for T2/T3 requires a stable URL, while random ports require an additional discovery and write-back mechanism, increasing complexity; a .env file for connection information rather than environment variables or a configuration service—persistent storage readable by multiple consumers (T2/T3), can be gitignored, and has zero dependencies, whereas environment variables alone do not persist across processes/launches, and a configuration service is overengineering for a single instance.

T2 makes four choices concerning the client form, caching strategy, error handling, and reason storage: a thin requests client rather than the py-gitea SDK or a custom asynchronous client—only 4 endpoints are needed, with no additional heavy dependencies, fully controllable request shapes, and easy mocking (Occam's razor), whereas an SDK introduces version coupling and unnecessary API surface, and asynchronous operation offers no benefit for a single session; a name→id label cache rather than querying on every call or requiring callers to pass ids—Gitea issue creation accepts label ids rather than names, caching avoids repeated GETs in each session, querying every time wastes requests, and requiring callers to pass ids exposes Gitea details to the user side; consistently raising exceptions rather than returning Result/nullable receipts—authentication failure/unreachability are unrecoverable environment problems, and explicit exceptions expose failures at the call site, whereas nullable receipts can easily be ignored downstream, silently losing issues; storing set_state's reason as a comment rather than discarding it or using a custom field—Gitea PATCH issue does not accept a reason field, comments preserve closure reasons for traceability, discarding them loses information, and Gitea does not support custom fields.

T3 makes four choices concerning seed pushing, rerun strategy, repository separation, and configuration sources: git push for the seed rather than uploading files individually through the API or uploading a tar archive—preserves real git history and commit objects, aligning with the developer agent's use of “real branches/merges,” whereas individual file uploads lack a unified commit and lose history semantics, and Gitea has no corresponding atomic interface for tar uploads; “skip if it exists” for reruns rather than force-pushing an overwrite or exiting with an error—protects evolving history and ensures idempotency, whereas force-pushing would lose developer agent output and error exits would make CI/reset workflows fragile; a harness repository separate from the issue working repository rather than a shared repository—separates the concerns of issues and harness evolution, with permissions and history independent of each other, whereas a shared repository would mix the issue flow with code evolution; reuse of T1's .env rather than script-specific arguments or separate configuration—a single source for OWNER/TOKEN, consistent with T2, without duplicating the configuration surface.

## Prior art

The three tasks share Gitea's official documentation: T1 follows the Docker installation guide (https://docs.gitea.com/installation/install-with-docker) and the command-line documentation (including admin user create / generate-access-token, https://docs.gitea.com/administration/command-line) to implement the local service and initialization scripts; T2 and T3 respectively follow the issues/labels/comments endpoints and repos/branches endpoints in the Gitea API documentation (all in https://docs.gitea.com/api/) to implement client calls and repository initialization. The three conventions in the CLAUDE.md architecture—“state destination: issue → Gitea,” “object being evolved: harness as a launchable program,” and “the dev side uses real branches/merges”—provide the direct basis for T1 and T3, respectively. T2's interface and data structure definitions build on spec-0001 (see T5 for IssueTracker/FakeTracker and T1 for IssueDraft/IssueRef), while T3's harness_template layout, launcher, and developer agent build on spec-0003; both obtain Gitea connection information from `backend/deploy/gitea/.env` produced by T1 in this group.

## Unresolved questions

<!-- TODO -->

## Future possibilities

<!-- TODO -->


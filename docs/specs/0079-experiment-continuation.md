---
number: "0079"
title: "Current experiment archive inheritance and appended iterations"
issue: 0
slug: experiment-continuation
summary: "Use the current complete archive as the frozen parent input; a new run first delivers feedback from the final round and then appends user rounds, reusing the unified entry point and recovery mechanism; legacy artifacts are unsupported."
tasks:
  - id: T1
    title: "Current archive source and contract verification"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/experiment/continuation/__init__.py
      - backend/ahe_beta/experiment/continuation/source.py
      - backend/ahe_beta/experiment/schemas/continuation-export-v1.json
      - backend/tests/test_experiment_continuation_source.py
    scope: "Read-only parsing of the current archive, final-round boundary, inputs, and file identity; historical formats are unsupported"
    acceptance: "Accept only complete current exports; reject corrupt, partial, identity-conflicting, or out-of-bounds packages; verify parent pairings against the authoritative plan"
  - id: T2
    title: "Canonical export and parent evidence report projection"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/experiment/continuation/export.py
      - backend/ahe_beta/experiment/continuation/evidence.py
      - backend/ahe_beta/experiment/continuation/forge.py
      - backend/ahe_beta/experiment/collection.py
      - backend/tests/test_experiment_continuation_export.py
      - backend/tests/test_experiment_continuation_evidence.py
      - backend/tests/test_experiment_continuation_forge.py
    scope: "Export the exact tree by commit; provide read-only parent evidence views, current report mappings, and redacted provenance proofs"
    acceptance: "Old main cannot contaminate the export; tree/mode/hash are correct; report retries are unique and do not mix up issue numbers; parent sessions do not count toward child metrics, and observations and authorization are consistent"
  - id: T3
    title: "Shared feedback delivery stage"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/loop/feedback_pipeline.py
      - backend/ahe_beta/loop/orchestrator.py
      - backend/ahe_beta/demand/triage.py
      - backend/ahe_beta/demand/divergent.py
      - backend/ahe_beta/demand/grouped_architect.py
      - backend/tests/loop/test_feedback_pipeline.py
      - backend/tests/loop/test_orchestrator.py
      - backend/tests/demand/test_triage.py
      - backend/tests/demand/test_divergent_gate.py
      - backend/tests/demand/test_grouped_architect.py
    scope: "Extract the concrete feedback pipeline; outer and role-internal layers share explicit prerequisites"
    acceptance: "Dependencies are consistent across both starting points and bootstrap external operation domains do not conflict; a stalled delivery does not start users; normal round ordering, recovery, and grade sealing contracts remain unchanged"
  - id: T4
    title: "Freeze inherited configuration and unify execution recovery"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
      - T3
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/experiment/config.py
      - backend/ahe_beta/experiment/schemas/experiment-v2.json
      - backend/ahe_beta/experiment/materials.py
      - backend/ahe_beta/experiment/context.py
      - backend/ahe_beta/experiment/workload.py
      - backend/ahe_beta/experiment/controllers/unified.py
      - backend/ahe_beta/experiment/controllers/feedback.py
      - backend/ahe_beta/experiment/controllers/runtime.py
      - backend/ahe_beta/experiment/engine.py
      - backend/ahe_beta/experiment/runtime.py
      - backend/ahe_beta/experiment/backends/local.py
      - backend/tests/test_experiment_continuation_config.py
      - backend/tests/test_experiment_continuation_lifecycle.py
      - backend/tests/test_experiment_continuation_workload.py
    scope: "source=parent configuration, atomic freezing, exact seed, stage role assembly, independent bootstrap recovery, and unified delivery completion criteria"
    acceptance: "A one-round continuation still delivers; compile new bindings for the same task/persona/interaction; do not copy the parent ledger; recovery does not repeat side effects; preserve normal semantics for old and new configurations and both backends"
  - id: T5
    title: "Bilingual experiment continuation tutorial"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T4
    relates-to: []
    parallel: false
    files:
      - docs/tutorials/experiment-continuation.md
      - docs/tutorials/experiment-continuation.zh-CN.md
      - docs/CONFIGURATION.md
      - docs/CONFIGURATION.zh-CN.md
      - README.md
      - README.zh-CN.md
      - CLAUDE.md
    scope: "Provide a complete tutorial from collecting a current parent run through child configuration, stopping and recovery, and further continuation; update support boundaries"
    acceptance: "Use only the unified entry point; keep Chinese and English commands consistent; clarify local and logical round numbers, lack of support for old packages, and fidelity to source facts"
  - id: T6
    title: "Contract and real dual-backend acceptance"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T4
      - T5
    relates-to: []
    parallel: false
    files:
      - backend/scripts/e2e-spec-0079-experiment-continuation.sh
      - backend/tests/test_experiment_continuation_contract.py
      - backend/tests/fixtures/continuation/current-parent-v1.json
      - .github/workflows/experiment-contract.yml
    scope: "Crash boundaries, repeated inheritance, and ordinary-path regression; empirical verification of non-empty delivery and archive cleanup on real local and E2B backends"
    acceptance: "Both backends demonstrate parent feedback→real delivery→additional user trial; current source remains unchanged, identities are new, and cumulative round numbers are correct; do not claim delivery without admission"
---

# 0079 · Current Experiment Archive Inheritance and Continuation Iterations

<!-- This file is maintained by the spec tool: frontmatter is structured source data (including the tasks DAG), and the body is a group-level rust-RFC nine-section overview. -->

## Summary

Add inheritance to complete experiment archives produced by the current unified entry point: create a new run that inherits the Harness, tasks, persona, and real user feedback from the parent experiment's final round, completes feedback processing and code delivery first, and then runs additional user rounds. The new run continues to use the existing check/prepare/run/status/stop/resume/collect/destroy commands; the parent experiment's identity, ledger, and archive remain unchanged.

The user has explicitly stated that compatibility with legacy experiment artifacts is unnecessary. This group supports only current schema 2 / workload contract 1 archives with the new export contract; it adds no historical layout adapters, source/replay selection, legacy script forwarding, or snapshot backfilling. Archive reading, parent evidence projection, and feedback execution each handle their own responsibilities, without introducing a second supervisor.

## Motivation

Current resume handles interruption recovery for the same run. A COMPLETED run is attached directly; recovery identity is fixed to run_id/config_hash/controller_sha/plan_hash, and completed rounds return sealed_sha directly. The final round of an ordinary experiment only runs user trials and does not process the feedback they produce. Resuming after changing the total round count in the parent configuration neither processes the final round's feedback nor respects input freezing.

The user needs this continuation flow: parent R5 completes user trials→create a child run→process R5 feedback and deliver→child user trials at logical R6. The current execution code, models, and backend may be frozen anew, but the parent's execution records must not be copied as successful records of the child run.

A producer-side gap in the current format also needs to be addressed: collection excludes .git, and workspace main may remain at the seed, with only origin/main fetched. Neither the existing working tree nor the initial materials/harness.tar.gz can prove the final version. Therefore, the current controller must export code at the final round's explicit SHA to provide verifiable input for subsequent work.

## Guide-level explanation

### 1. Complete and collect the parent experiment first

Run the parent experiment normally to COMPLETED using the current unified entry point, then execute collect. The new version puts a Harness export explicitly bound to the final round's SHA, feedback, and provenance proofs into artifacts.tar.gz, and reports continuation_ready in the collection receipt. An archive may be used as a parent source only when COMPLETE, experiment_complete, and continuation_ready all hold. Destroying the parent compute resources does not affect use of the collected archive.

This group does not retroactively upgrade old frozen controllers. Past archives lacking the new export contract are explicitly reported as unsupported; the final code is not guessed from caches or the working tree.

### 2. Declare inheritance in the child experiment

The child configuration remains a complete schema 2 configuration. Fill in runtime, models, roles, policies, and the additional round count according to current rules, changing only the input source to:

```json
{
  "harness": {"source": "continuation"},
  "workload": {"source": "parent"},
  "continuation": {
    "archive": "../parent/artifacts.tar.gz",
    "sha256": "64-character parent archive SHA256"
  },
  "rounds": {
    "count": 1,
    "sessions_per_round": 4,
    "max_parallel_users": 4
  }
}
```

This is a snippet to incorporate into a complete configuration, not a complete runnable file. The first version inherits the task/persona/interaction pairings from the parent's final round as-is and repeats these pairings for each additional round; sessions_per_round must match the number of users in the parent's final round. Changes to models, backends, or policies are declared explicitly in the child configuration, and parent-child differences are recorded. The first version does not support using this mechanism to replace tasks or personas; use an ordinary new experiment when a different workload is needed.

No new import startup flow is needed; continue using the existing commands:

```bash
python backend/scripts/experiment.py check --config child.json --offline
python backend/scripts/experiment.py prepare --config child.json --secrets-file .env.experiment
python backend/scripts/experiment.py run CHILD_RUN_ID --secrets-file .env.experiment
```

check returns the parent identity, final-round SHA, feedback user count/report count, input summary, and gaps; prepare atomically freezes inherited inputs; run delivers the parent feedback before starting users. Credentials come from the child profile, not the parent .env, old tokens, or the parent's Gitea address.

### 3. Rounds and stop/recovery

rounds.count represents the number of additional user rounds. When the parent's final round is logical R5, the child's base_round=5, and count=1, the child has local_round=1 internally and lineage_round=6 externally. Feedback initialization is the continuation_bootstrap stage and does not count as an additional user round. When multiple rounds are appended, intermediate additional rounds deliver normally, while the final round still only runs trials.

Child stop/resume uses the existing entry points to recover this initialization and the additional rounds. The parent run's COMPLETED status and the users-only nature of its final round remain unchanged. Parent sessions do not count toward child session counts, child scores, or additional model usage.

## Reference-level explanation

### 1. Module boundaries and dependency direction

```text
current archive → source validation → existing material freezing
                         ↓                        ↓
                read-only parent evidence → unified controller
                                                  ↓
                              shared feedback pipeline → ordinary user loop
```

- experiment/continuation/source.py: Understands only the current archive and export contract, validates and selects the parent's final round, and returns data; does not import backend/controller or run archive code.
- continuation/export.py: Exports the exact Harness tree and provenance proofs for a specified commit; called by the frozen controller shared by both backends; does not guess code through provider branches.
- continuation/evidence.py, forge.py: Provide read-only views of parent sessions and report mappings in the new repository, respectively; depend only on materials and existing store/tracker operations.
- loop/feedback_pipeline.py: Extracts concrete demand→owner→delivery→seal operations from the existing Orchestrator; has no knowledge of archives, lineage, or paths.
- materials/context/unified controller: Freeze inputs, pass non-sensitive context, and assemble execution, respectively. The backend continues to build workspaces, manage processes, and clean up resources according to normal configuration, without adding a “parent experiment recovery” branch.

controllers/feedback.py is the concrete assembly function for stage roles. It reuses existing definitions and callbacks and explicitly receives the evidence store, recovery domain, round provider, and grouped artifact root; it is not a generic agent factory. It lets bootstrap and ordinary stages be assembled independently, avoiding large blocks of role construction code in unified.py or temporary modifications to private instance fields.

Do not add an importer plugin system, a general workflow platform, a separate launcher, or a new model invocation layer. The public entry point adds only a configuration source; check/prepare reuse the same source validator.

### 2. Configuration, archive, and material freezing

continuation is an optional object with only two fields, archive/sha256. When present, it requires harness.source=continuation and workload={source:parent}; all three must appear together, and another Harness or explicit task input must not be mixed in. When omitted, existing configuration hashes, fields, and behavior remain unchanged, and no default continuation is added.

Accept only the current collect output as a single-layer artifacts.tar.gz: schema_version=2, workload_contract_version=1, a versioned continuation export, and consistent original controller invocation/recovery/collection identities. Read the collection.files integrity manifest, corresponding materials, and selected sessions. Reject unknown versions, PARTIAL, stopped/failed parent experiments, missing exports, duplicate/out-of-bounds/link/special paths, and packages exceeding extraction budgets. Do not support tar.zst, recursively packaged complete experiments, or arbitrary scripts inside packages; task source archives declared by the registry, inner Harness exports, and observation bundles remain normal materials and are checked against their respective contracts and budgets.

The parent boundary is the last round in which all expected users have completed and which has been sealed; its user_sha/sealed_sha must be identical. The user set is determined by the frozen plan and recovery units, not inferred from file counts or mutable labels. Completion criteria read the collection's controller receipt, nonce, invocation, and recovery; they do not require the initial status field in the immutable manifest to be updated to COMPLETED. The outer archive SHA is the expected SHA supplied by the child configuration; collection.files inside the package verifies content, and the archive is not required to record its own hash.

Complete session payloads, corresponding task_digest/persona, and explicit report associations are required. Inheritance is allowed when there are no reports, but the count must explicitly be zero; fictional feedback must not be generated. When pending reports exist, the child must have at least one triager and one architect; parent feedback must not be silently skipped because roles are set to zero. If the parent is itself a continuation run, also verify that its bootstrap completed and its first user SHA equals the bootstrap sealed SHA before accepting its final round.

prepare copies verified inputs from the parent manifest's material registry, including original task source archives, instruction, setup/requirements lock, and persona cards, and reuses the normal task catalog and workspace preparation without relying on parent host paths or the parent's live sandbox. Preserve task records and packages as-is, including logical source/tasks/ID paths; although the source directory is not in the parent collection package, it can be reconstructed from the source_archive referenced by the registry. Do not rerun _freeze_task, guess the host source directory, or change package paths in a way that changes task_digest.

export records the canonical JSON digest of selected persona cards, the original library hash, and the roster strategy; inheritance takes the original cards from the frozen card library, not the display persona from Session. The child may save only selected cards, but must identify them as a selection from the original library and must not claim that the entire library file is byte-for-byte unchanged. Take only the actual pairings from the parent's final round and compile a new R1..N plan according to the child count; reuse existing binding validation and do not pass off the parent plan_hash as the child plan_hash.

Add an explicit inherited-pairs input path to the workload compiler, sharing binding generation/validation with ordinary compilation. Parent pairings and digests go into the continuation material record in the new manifest; read_session_plan must revalidate from these frozen pairings. The configuration still stores the user-declared source:parent; do not write derived runtime state back into the configuration or fabricate external task_package paths.

Register inherited files as relative paths + hashes under materials/continuation; the child still freezes the current controller/OpenAgents source and model policies. manifest.lineage contains at least parent_run_id, parent_config_hash, parent_controller_sha, parent_plan_hash, parent_archive_sha256, base_round, parent_user_sha, parent_tree_id, and declared model/backend/policy differences. Parent resources, checkpoint identity, authorization grants, and secret profile are not copied.

### 3. Final Harness export by the current producer

Add continuation-export-v1.json, recording the final-round SHA/tree ID, source archive and SHA-256, per-tracked-file content digests/Git modes, and selected final-round and session/material proofs. The controller exports at the SHA specified by the ledger only after the ordinary loop has fully completed; it does not infer the code from workspace main/HEAD or the final cache. Allow normal Git tree files and executable modes; reject links/submodules/special modes without silently dropping files.

Place export files in the normal collection directory without overwriting materials/harness.tar.gz. If objects are missing, files are private/unsupported, or evidence is inconsistent, record unavailable while preserving the validity of the ordinary experiment's existing results; collect may complete, but continuation_ready=false, and subsequent check explicitly rejects inheritance. COMPLETE and inheritability are separate fields.

The collector retains an explicit evidence projection record: when existing credential redaction occurs, record the original file hash, archive hash, and credential_redaction reason, without recording credential values. A parent Session may be used as declared redacted evidence, but its archived bytes must not be claimed to be the original execution bytes; runnable materials such as task/Harness/persona must exactly match their original hashes, and inheritance is not allowed if redaction changes them.

The first version uses the exact source tree without carrying parent Git history. The child creates a new seed commit whose commit message body binds the parent Harness commit, ensuring that parent and child commits differ even when consecutive generations have the same tree, commit identity, and second-level timestamp; the receipt explicitly states that parent_commit and child_seed_commit differ, and the child Git tree must equal parent_tree_id. The outer collector uses write_bytes and must not depend on outer tar modes; restore executable modes from the inner export inventory. Index construction must include files tracked by the parent but ignored by .gitignore, avoid clean filters/.gitattributes changing blobs, and verify both individual blob hashes and write-tree, not merely run git add .. The continuation seed does not rewrite the parent .gitignore; runtime exclusion rules go in .git/info/exclude, and hooks are installed after the seed. Ordinary builtin/archive seeds retain their existing semantics.

### 4. Parent evidence and report projection into the new repository

The child run creates a new repository of its own. Complete seed and remote initialization first, then project pending reports from the parent's final round, preventing _reset_to_initial from closing imported reports. Create current reports; do not replay parent proposal/ready/PR/merge operations. Parent forge state and comments remain read-only archive data, and the openagents/ready label is not inherited. Closed, rejected, or delivered reports remain background context and are not automatically reopened as new work.

Reports use parent archive/repo identity/number as the source namespace, preserving original text and hashes; the create_issue_once operation key comes from the child identity and source report digest. After actual number assignment, save the source→current issue_map; even if the new number equals the parent number, they must not be confused. # numbers/URLs in the original text are displayed as historical references and are not globally replaced in natural language; current executable references are generated only from the structured mapping.

The import receipt retains the repo ID, child seed, source report hash, new number/URL, and status. If the remote issue was created but not yet written back locally, recovery reconciles using marker/payload; external content changes or identity conflicts raise an error, and retries are not completed by creating another issue.

ContinuationEvidenceView wraps the child SessionStore and read-only parent materials. load/find_session_id_by_issue/load_user_feedback_envelope resolve parent SIDs using the explicit issue_map and preserve parent provenance; they do not call parent save/reconcile/rebuild_index. The bootstrap role index uses the selected parent boundary; the current issue_numbers in the derived view are generated from the mapping, while source refs are retained separately. Roles in ordinary user turns and Metrics use the current index. Parent sessions are not written to child sessions/index and do not become user attempts in this run; SID conflicts are rejected rather than overwritten.

Native observation bundles are copied byte-for-byte with their hashes to the child's current observation_root/SID, retaining the parent manifest identity so that both the existing ObservationProvider and delivery_evidence can read them. New grants are created only from the mapping and authorized SIDs; parent grants are not copied. If the collector redacts any bytes in a bundle, the nested hashes in the original manifest become invalid, and the bundle must be unavailable; it cannot be called natively faithful after rewriting the original manifest. If there is no valid observation, keep it unavailable; do not reconstruct fake logs. Preserve invalid/skipped/unverified_accept, rejection reasons, and redaction declarations; do not turn subjective impressions into confirmed technical facts.

### 5. Shared Feedback Phase and Bootstrap Recovery

Extract recoverable demand, owner, delivery wait, and seal into one concrete FeedbackPipeline. Ordinary turns use prerequisite=users; inherited initialization uses prerequisite=feedback_imported. It depends on roles, recovery, fetch/wait, integrity_guard, and SHA resolution/checking, and does not accept archive or provider objects. Preserve the existing timing of checking orchestration repository integrity before sealing; this also applies to bootstrap. A successful seal must not be recorded before discovering out-of-bounds modifications.

The existing hardcoded users dependencies in the Triager and Divergent inner units must be bound consistently to the same explicit feedback_dependency; the normal path remains users. Architect/grouped/Owner reuse the existing recovery bindings, keeping the order triage∥divergent→architect→owner→delivery_wait→seal. Do not extend RecoveryStore into an arbitrary workflow.

Bootstrap uses a separate RecoveryStore at checkpoints/continuation-bootstrap. Its identity comes from the child run/config/controller and the digest of the frozen initialization inputs; the internal positive round=1 is only for this namespace, not a parent round or child user round. The starting stage is feedback_imported; do not fabricate a successful users stage. The receipt explicitly identifies the phase, source boundary, mapping, and input hash.

External side effects must also be isolated: bootstrap operation keys/UsageContext.operation use an explicit continuation-bootstrap prefix, while ordinary turn keys remain unchanged. Separating ledger directories alone is insufficient to avoid create_issue_once/model-output key collisions between bootstrap round1 and user round1 in the same repository. Grouping artifacts also use a separate phase directory. Parent round-* labels are preserved in source metadata and do not enter current execution labels; bootstrap roles' round_provider returns None, while the recovery context still uses its internal positive round1. Ordinary phases restore the actual local round, preventing filter_current_round from mistakenly dropping parent reports or mixing bootstrap proposals into ordinary turns.

The shared phase extraction preserves the ordinary persistence contract: stage=round_sealed, key=operation_key(local_round,"round_sealed","stage-marker"), input={user_sha,sealed_sha}, observed_postconditions.completed, and the original dependency relationships. Existing grade and resume directly verify these fields; do not change them to seal or replace ordinary keys for the sake of consistent terminology.

Verify seed/projection→parent evidence view and bootstrap recovery binding→shared pipeline→fixed admission set and delivery terminal state→new main is a descendant of child_seed→save the sealed SHA and complete atomically. Even with zero admissions, record no_admissions and a valid seal. If blocked, stop at bootstrap and do not start new users early.

Resume first reconciles the initialization receipt and existing external side effects. When bootstrap is complete, do not rerun the LLM or recreate reports or deliveries. The two phases create separate instances through the same concrete role assembly function, passing the corresponding store/recovery/round_provider/artifact root; do not switch by modifying private object attributes. Then call the existing user loop. Completed parent users are not copied into the child ledger.

Delivery is uniformly enabled when count>1 or continuation_present; the role roster, Vigil startup, and launch readiness for both backends use the same semantics. Even when appending only one round, parent feedback must be deliverable. Engineering CI remains determined by the child configuration; the E2B CI scope is not expanded by this work.

For continuation runs, engine._completion adds criteria requiring bootstrap completion, identity consistency, matching input and mapping hashes, and a valid sealed SHA, and requires main ledger R1.user_sha == bootstrap.sealed_sha to prove that the new users actually tried this delivery, in addition to the existing sealing conditions for user rounds 1..N. Ordinary runs do not read this field. status/logs return the bootstrap phase and local_round/lineage_round. batch/grade continue to use this run and local numbering, counting only new predictions.

### 6. Both Backends and Subsequent Continuations

Both backends read the same frozen catalog, persona, parent evidence, and bootstrap inputs. Dependency installation, Git task preparation, and normal task environment verification remain the responsibility of the existing backend; this work does not promise offline installation or arbitrary environment equivalence across backends. When moving from parent local→child E2B or vice versa, if the target backend does not support the original task, check/prepare must explicitly reject it; do not substitute a simplified task.

Child collect retains lineage, issue_map, the bootstrap receipt, necessary parent evidence, and the child final-round export. Ancestor records contain only hashes/identities/necessary references and do not recursively nest complete parent archives. The export explicitly records local_round=parent count, lineage_round=parent base_round+parent count, and the parent’s own user units for that round. A successor selects only the direct parent's final round; it does not reselect ancestor sessions or import already processed ancestor reports.

New child base_round = parent.lineage.base_round (0 if there is no lineage) + parent.config.rounds.count, cross-checked against parent export.lineage_round; new child lineage_round=base_round+local_round. For example, parent R5→two new child rounds are logical R6/R7→one further appended round is R8. Parent materials' original text/bytes and hashes are not relabeled as current execution during repeated inheritance.

### 7. Task DAG and Acceptance

T1: read/validate current archives; T2: terminal-state export and evidence/report projection, depending on T1; T3: independently extract the shared feedback pipeline and test normal-path regressions; T4: integrate configuration/freeze/controller/lifecycle, depending on the first three; T5: write bilingual tutorials and perform a capability audit, depending on T4; T6: complete contract and real dual-backend acceptance, depending on T4/T5. The file mutual exclusion list is in the frontmatter. End-to-end script backend/scripts/e2e-spec-0079-experiment-continuation.sh.

| Acceptance | Required observations |
| --- | --- |
| Source and identity | New export contract matches the final-round SHA/plan/receipt; PARTIAL/FAILED/missing export/unknown version/corrupt or out-of-bounds packages are rejected |
| Final-round pairing | Use the ledger's completed user set, not file counts; task/persona/interaction retain their original content identities, and the new plan is 1..N |
| Harness | Even if local main is old, export using the explicit final-round SHA; child tree is exactly identical, parent/child commits are distinguished, and mode/ignore are not silently changed |
| Evidence mapping | Identical numbers do not cross sources; report retries are unique; parent Session provenance is unchanged and excluded from new metrics; original observations reach both demand and delivery readers |
| Redaction and invalid feedback | Preserve original/archive hashes and reasons; invalid/missing logs do not become valid; inheritance is prohibited if runnable materials change |
| Recovery | Interrupt separately after issue creation, after LLM output is saved, during delivery wait, and after bootstrap is sealed; no duplicate side effects and no premature start of new users |
| Operation domains and sealing contract | Remote deduplication keys for bootstrap and ordinary R1 do not collide; grouping/round filtering does not mix sources; original grade sealing fields remain unchanged; new R1 actually tests the bootstrap sealed SHA |
| Ordinary runs | Without continuation, old hashes, single-round Vigil remaining disabled, the final round of multi-round runs, resume, batch, and grade retain their original contracts |
| Actual dual-backend execution | Current parent run→real parent report processing→at least one admitted issue and actual OpenAgents delivery→child user trial; zero admissions cannot substitute for nonempty delivery |
| Subsequent continuation and cleanup | Re-inheriting the child archive shows correct cumulative round numbering without recursively nested packages; parent bytes remain unchanged, and cleanup targets only child resources |

Small fixtures must cover final-round subsets of multiple tasks/personas, ignored tracked files and executable mode, redaction affecting native observations, and R8 numbering for parent R5→two child rounds→one third-generation round. They verify actual content and execution ownership, not merely the presence of configuration fields.

Model output cannot guarantee admission; acceptance must explicitly identify actual issues and PR/sealed evidence. Zero admissions can only be recorded as passing verification of that branch. Test fixtures use only small redacted packages in the current format; do not commit old experiment artifacts or execution scripts. Repository-wide pytest, Ruff, configuration contracts, spec checks, and an actual acceptance report are merge conditions.

## Drawbacks

Precise final-round code export, parent evidence storage, and report mapping increase archive size. Carry only the selected final round and necessary forge context, and record ancestors by digest to control growth without losing evidence needed for the current run.

Child Git commits do not retain parent history, so code equivalence must be recorded by tree identity. The target backend must still support the normal preparation conditions for the parent task; changing models or backends affects comparability, and lineage displays the differences without automatically concluding convergence.

Archives without the new export are incompatible, consistent with the user's narrowed scope; already frozen old controllers are not retroactively upgraded.

## Rationale and alternatives

Choose “current archive+new run+independent feedback initialization” to preserve parent facts and the existing lifecycle while allowing explicit model changes for continuations.

Do not modify parent rounds/hash and then resume, or copy users or delete seals: completed rounds will not process additional demand, and doing so would confuse execution ownership. The independent bootstrap domain reuses RecoveryStore and existing side-effect reconciliation, avoiding wholesale renumbering of user plans, scoring, and batch.

Do not add a generic archive adapter or standalone import command: there is currently only one producer and one input format, and existing check/prepare can perform validation and freezing. Nor should the local/E2B backend restore the parent process or revive the parent repo; the new run follows current resource governance.

Choose a source tree snapshot rather than the entire Git history; export by parent commit and verify the tree, preserving the original source facts while preventing old hooks/config/PR history from entering the execution surface. Explicitly map different seed SHAs; do not falsely claim that the SHAs are identical.

The first version's workload is fixed to inherit the parent's final round, reducing ambiguity in task conversion and input overrides. If task changes are genuinely needed later, design explicit fork semantics then; do not add a set of generalized migration switches to the current interface.

## Prior art

All necessary background is explained in place. Code evidence comes from: the completion short-circuit and existing demand/delivery recovery in Orchestrator._run_recoverable_round; RecoveryIdentity and begin_unit dependency consistency; SessionStore provenance/index/evidence reads; atomic freezing in prepare_materials/verify_materials; engine._completion sealing criteria; Observations grants and delivery asset reads.

The existing unified controller handles assembly for both backends. The current task catalog and plan already separate logical identity from provider coordinates, and their original material registration can be reused. The collector's exclusion of .git and the possibility that the seed working tree is stale demonstrate the need for a standardized export; the fact that the current archive “appears to contain code” cannot be treated as proof that it can be inherited.

## Unresolved questions

This draft is narrowed to the current format, a completed final round, a new identity, a fixed inherited workload, explicit model/backend changes, exact tree export, and an independent bootstrap domain; no old-format compatibility or historical scenario recovery options remain open.

Implementation must empirically verify native observation validation against the parent manifest, tree/mode/ignore fidelity, actual nonempty delivery on both backends, repeated inheritance, and crash reconciliation. If verification fails, revise the design and present evidence; do not bypass identity or fabricate logs.

## Future possibilities

Possible future additions include UI parent-child comparison, forks that explicitly change the workload, parent boundaries before the final round, and reevaluation of existing feedback. Arbitrary snapshot/live service/private task capabilities still belong to the task environment layer; this work adds no bypass and does not couple those capabilities to continuation from current archives.

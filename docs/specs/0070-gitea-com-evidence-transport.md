---
number: "0070"
title: "Gitea.com-Compatible Evidence Publishing and Joint Preflight"
issue: 0
slug: gitea-com-evidence-transport
summary: "Retain self-hosted Gitea's gzip behavior, add ZIP publishing, restricted signed downloads, and reader-side capability validation to ensure compatibility with existing evidence and recovery."
tasks:
  - id: T1
    title: "Attachment Capability Parsing and Restricted Downloads"
    status: done
    priority: P1
    tags: []
    depends-on: []
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/tracker/gitea.py
      - backend/ahe_beta/tracker/attachment_transport.py
      - backend/tests/tracker/test_gitea_evidence_transport.py
      - backend/tests/tracker/test_gitea.py
      - backend/tests/tracker/test_gitea_observe.py
      - backend/tests/tracker/test_gitea_timeline.py
    scope: "Parse the actual upload type and site rules, retain same-origin downloads, and add fixed Gitea.com/R2 policies with bounded unauthenticated external requests."
    acceptance: "Self-hosted 200 and hosted single-hop pass; select ZIP under Gitea.com rules; reject API/malicious-domain/second-redirect/timeout/authentication-leak negative cases."
  - id: T2
    title: "Dual-Format Publishing and Frozen Transport Records"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/demand/delivery_evidence.py
      - backend/ahe_beta/observations/transport.py
      - backend/tests/demand/test_delivery_evidence.py
      - backend/tests/observations/test_transport_profile.py
    scope: "Keep the default gzip bytes/handles unchanged, and add deterministic single-file ZIP and independent profiles; restore old directories as gzip without changing the framework contract."
    acceptance: "Existing gzip bytes and handles remain unchanged; ZIP read-back summaries, retry reuse, authorization scope, size limits, and old-profile restoration tests pass."
  - id: T3
    title: "Live Delivery Runtime Capability Preflight"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T1
      - T2
    relates-to: []
    parallel: false
    files:
      - backend/ahe_beta/experiment/controllers/ordinary.py
      - backend/ahe_beta/loop/sim_user.py
      - backend/ahe_beta/observations/preflight.py
      - backend/tests/test_run_vigil.py
      - backend/tests/loop/test_sim_user.py
      - backend/tests/observations/test_transport_preflight.py
    scope: "Check the new-path capabilities in the actual executable/image and reused container, disable self-updating, freeze the profile before starting the model or dispatching an issue, and wire the container to a public address."
    acceptance: "The old gzip path does not require the new command; block on old readers/bad capabilities/incorrect images/frozen-configuration drift before model invocation and issue dispatch; both sim_user entry points and recovery pass."
  - id: T4
    title: "On-Demand Public Egress and Image Wiring"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T3
    relates-to: []
    parallel: false
    files:
      - backend/deploy/gitea/docker-compose.yml
      - backend/deploy/gitea/egress-proxy.conf
      - backend/deploy/gitea/egress-gitea-com.conf
      - backend/deploy/experiment/docker-compose.yml
      - backend/deploy/experiment/egress-proxy.conf
      - backend/deploy/experiment/egress-gitea-com.conf
      - backend/deploy/vigil/entrypoint.sh
      - backend/deploy/vigil/build.sh
      - backend/deploy/vigil/observation-runtime.json
      - backend/tests/test_vigil_build.py
      - backend/tests/experiment/test_evidence_egress.py
    scope: "Explicitly enable restricted proxy rules for the hosted profile while retaining the old egress default; build and validate the actual new-reader image and record the real version."
    acceptance: "Default network permissions are not expanded; the explicit hosted path goes through a proxy to Gitea.com/R2; spoofed targets are rejected, and the final image capabilities match the record."
  - id: T5
    title: "Cross-Repository Acceptance and Joint Release"
    status: done
    priority: P1
    tags: []
    depends-on:
      - T2
      - T3
      - T4
    relates-to: []
    parallel: false
    files:
      - backend/scripts/check_observation_contract.py
      - backend/scripts/check_gitea_evidence_transport.py
      - backend/tests/test_observation_contract.py
      - .github/workflows/ci.yml
      - release/compatibility.json
      - docs/QUICKSTART.md
      - docs/CONFIGURATION.md
      - docs/RELEASING.md
      - backend/deploy/README.md
    scope: "Add real producer/reader offline contracts and explicit live probes, and update the reader-first supporting SHA/deployment records and usage instructions."
    acceptance: "The two repositories' pinned-version offline contracts pass; self-hosted/Gitea.com and E2B/container actual prepare operations produce read-only authorization evidence; live results are redacted and make no model calls."
---

# 0070 · Gitea.com-compatible evidence publishing and joint preflight checks

<!-- This file is maintained by the spec tool: frontmatter is the structured source data (including the tasks DAG), and the body is a group-level nine-section rust-RFC overview. -->

## Summary

Status: Approved by the user; candidate implementations in both repositories and offline/real transport verification are complete; the official release has not yet been performed. Tasks marked done indicate that implementation and candidate verification for this version are complete; the official reader SHA/digest must be filled in after the reader is merged, built, and retested first. Candidate images built from a local dirty working tree must not be treated as released versions.

Add Gitea.com evidence publishing support to AHE-Beta while preserving existing gzip behavior, historical handles, and experiment recovery for self-hosted Gitea. The corresponding reader is OpenAgents `0092-gitea-com-evidence-reader.md`; the two repositories align through the transport contract and joint tests defined in this file, without vendoring each other's business code or adding an attachment hosting service.

The delivery scope of this group is “authorized evidence can be uploaded, read back and verified, and read by actual OpenAgents”; continued execution of an experiment process does not constitute success, and verification of the new feature must not be mixed into the currently running fixed-version N1 experiment.

## Motivation

A new-user trial on 2026-09-29 found that attachment rules on internal Gitea 1.22.6 allow .gz, with direct downloads returning 200; Gitea.com currently rejects actual gzip uploads (422), allows valid ZIP uploads (201), and returns 303 redirects to signed R2 URLs for attachment downloads. Real gzip round trips on the internal instance and from E2B to the internal instance have both passed.

The current publisher hardcodes gzip compression and .json.gz naming in `demand/delivery_evidence.py`, while `tracker/gitea.py` requires .gz in the allowlist during preflight, uses a fixed upload MIME type, and prohibits download redirects. The Owner adds delivery labels only after evidence is published and read back for verification; this ordering must be preserved. Existing local observations and authorization structures do not depend on the hosting provider and do not need to change.

The old OpenAgents reader is fixed to gzip; even if the publisher successfully uploads ZIP, the reader still degrades to “evidence unavailable” and continues working. Therefore, actual reader capability checks and joint verification that files are read are required; merely fixing the upload extension or ignoring preflight checks is insufficient.

## Guide-level explanation

Users with existing self-hosted Gitea continue using their original credentials and startup method: when the server allows gzip, prefer the original gzip format, with no migration required for existing attachments or Issues; old OpenAgents versions can continue reading through this path.

Gitea.com users still provide only their own site account/token and existing E2B/model configuration. New runs select ZIP according to site rules and confirm reader capabilities in the actual delivery environment. Errors should identify the stage and an actionable remedy, such as “The current OpenAgents version does not support ZIP; upgrade the delivery runtime,” rather than resulting in “the experiment has started but the developer has no evidence.” Network or permission failures must not be interpreted as unsupported formats.

This group does not rewrite the E2B launcher, automatically deploy public Gitea, or implement the unfinished optional experiment backend design (0069). It only integrates the existing runnable subprocess/E2B and container evidence paths; other issues with the complete new-user Quick Start are handled separately.

## Reference-level explanation

### Shared transport contract for both repositories (this section must remain consistent)

- The inner JSON's `format` remains `auto-designer:observation-evidence-v1`; issue, sessions, manifest, file paths, and digest semantics remain unchanged; Agents must not parse the transport protocol.
- Issue machine handles continue using `asset_id/name/sha256/bytes`. Handles from old gzip publications gain no new fields; a missing `encoding` means gzip. New ZIP handles must include `encoding: "zip"`; the reader also allows explicit `encoding: "gzip"`. Unknown values or mismatches between declarations and actual magic bytes must be rejected, without automatic guessing or fallback.
- `sha256` and `bytes` always verify the actual downloaded compressed attachment. The transfer limit is 4,000,000 bytes, and the decompressed limit is 24,000,000 bytes; limits must be enforced during actual reads, rather than trusting only the server or ZIP metadata.
- A ZIP contains exactly one regular file, `evidence.json`, using UTF-8 and DEFLATE; reject extra or duplicate entries, directories, links, encryption, and other compression algorithms. Read this entry only in memory with bounds, without extract/extractall. The publisher fixes the entry timestamp at 1980-01-01 00:00:00, file metadata, and compression level 6, ensuring identical bytes on retries within the same fixed publishing runtime; inner JSON serialization follows the existing rules.
- `same-origin-v1` preserves the existing self-hosted Gitea HTTP/HTTPS direct 200 path. The new `gitea-com-r2-v1` applies only to instances whose configured origin is exactly `https://gitea.com`, with default port 443 and no subpath; suffix matching must not be used to allow impersonating sites.
- Always first verify through the authenticated Gitea API that the attachment belongs to the current issue, then request the same-origin `/attachments/{uuid}`; do not use external links in the body or `browser_download_url`. Only a 302/303/307/308 response from this authenticated attachment may enter a single restricted redirect; the target must use HTTPS, default port 443, no userinfo/fragment, and a hostname that exactly satisfies the full rules of `^[a-f0-9]{32}\.r2\.cloudflarestorage\.com$`. Reject other storage domains, IP literals, ports, or second redirects. This boundary is a fixed hosted-domain policy that relies on normal DNS/TLS and deployment proxies; it does not provide general-purpose downloading from arbitrary URLs.
- Object storage uses a new request without Gitea Authorization or Cookies, without inheriting session or .netrc authentication; retain explicitly configured network proxies. The signed query is used only for this request and must not be written to logs, exception bodies, or persistent state. Redirect hops share a single total 15-second budget per attachment download; accept only a final 200 response and continue verifying byte count and digest; API requests still prohibit redirects.
- The capability command is `openagents observation-capabilities --json` and returns a single JSON object: `schema=openagents-observation-reader-capabilities-v1`, `marker=auto-designer:observation-evidence-v1`, `encodings=[gzip,zip]`, `zip_profile=single-evidence-json-v1`, `download_policies=[same-origin-v1,gitea-com-r2-v1]`, and the two byte limits above. Invocation requires no project, credentials, or network; it does not self-update, create files, or call models.
- The capability command must execute inside the actual delivery executable/image; set the existing switch `OPENAGENTS_NO_SELF_UPDATE=1` when querying so that even older versions that do not recognize the command cannot self-update first. Official delivery processes on the new path must likewise disable self-updates during execution and record the actual executable/image identity. The old pure gzip + same-origin path does not mandate the new command; missing, unknown, timed-out, or budget-mismatched capabilities for ZIP or R2 paths must explicitly block execution before task dispatch/model calls.

### Publishing, selection, and recovery

New transport selection uses correctly parsed attachment configuration: normalize case for comma-separated extensions, match MIME types after removing parameters, and handle the allow semantics of application/gzip, application/x-gzip, application/zip, empty values, and */*; the presence of application/octet-stream alone does not imply that .gz files actually uploaded as application/gzip are allowed (Gitea.com has been verified to reject them). Prefer gzip when it is effectively allowed, otherwise ZIP; fail explicitly if neither is supported. Do not use 401/403, timeouts, or 5xx as grounds for selecting ZIP. Subsequent actual upload and readback are the final determination; conflicts between site declarations and observed behavior must report the discrepancy rather than automatically relaxing validation.

Keep the original `build_package` call defaulting to gzip, and ensure that the original input produces the original gzip bytes in the same publishing runtime. ZIP changes only the outer compression, followed by deterministic naming based on the actual attachment digest. Repeated publishing preferentially reuses an asset with the same name, updating the machine handle and delivery labels only after reading and verifying it; transport failures preserve the original proposal, authorization, and evidence archive, and retries do not create duplicate deliveries.

The repository/format/max_transfer_bytes object returned by the existing `preflight_observations()` retains its original shape because both sim_user entry points compare it in full against `.framework-contract.json`. The new `.transport-profile.json` separately persists the schema, repository identity, encoding, download_policy, and budgets, without storing tokens or signed URLs. Determine and persist the profile before starting user or developer model calls for this round; recovery of the same experiment reuses the selected profile and does not silently switch formats when site configuration changes.

When an existing observation directory has an old framework contract but lacks a profile, interpret it as the old gzip + same-origin configuration; after verifying that it remains usable, the profile may be written atomically without rewriting the old contract/attachments. If the site no longer supports the old path, explicitly stop recovery and recommend a new experiment identity, without mixing old and new evidence. Pass format selection information to the tracker/publisher through explicit configuration; do not let bare `publish_delivery_evidence` automatically enable ZIP without capability checks.

### Actual runtime preflight checks and proxies

The old pure gzip path retains existing behavior. Before starting/reusing vigil, the new path checks the actual reader: subprocess/E2B invokes the openagents executable that will actually be used; new containers execute the offline capability command by overriding the entrypoint using a fixed image ID; reused containers check their actually installed version rather than substituting host source code. The capability process has a 10-second timeout and a 16 KiB stdout limit; fail explicitly if the command is absent or its output does not conform to the schema.

When containers access Gitea.com, only this profile makes the container-side Gitea URL use the public https://gitea.com in the absence of an explicit override; the existing localhost→http://gitea:3000 mapping remains. Both egress-proxy templates need an explicitly enabled extended allowlist for Gitea.com/R2; the original mode must not expand egress by default. The extension is limited to port 443, exact gitea.com, and the specified R2 hostname, without allowing all of cloudflare.com. Proxy allowances do not replace client-side target validation. Preflight failure must prevent developer task dispatch from starting.

### Task DAG and file allocation

| Task | Responsibility | File ownership | Dependencies |
|---|---|---|---|
| T1 | Gitea capability parsing, MIME, restricted downloads | tracker/gitea.py, new attachment transport module, and dedicated tracker tests | None |
| T2 | Dual-encoding publishing, profile persistence, and legacy recovery | demand/delivery_evidence.py, new observations/transport.py, publishing/profile tests | T1 |
| T3 | Actual reader capability preflight checks and lifecycle wiring | backend/ahe_beta/experiment/controllers/ordinary.py, loop/sim_user.py, new observations/preflight.py, lifecycle tests | T1, T2 |
| T4 | Container public-network wiring and on-demand egress | Both deployment proxy/Compose setups, vigil build/entrypoint/image records, deployment tests | T3 |
| T5 | Cross-repository CI, live probes, joint versions, and documentation | Joint check scripts, integration tests, CI, release/compatibility.json, usage/release documentation | T2, T3, T4 |

Cross-repository release dependencies must not be written as Task IDs that mistakenly refer to this repository: OpenAgents 0092 first completes and releases a compatible reader → this repository's T5 verifies it using the actual commit SHA/image → this repository enables the new path. Do not fabricate future commits or image digests in the spec; record actual verified pins during implementation.

This version retains the old configuration baseline `openagents.integration_commit` and adds `observation_transport.reader_release_commit` (currently null). CI supports manually supplying an actual full reader SHA to run the new contract; after the official reader pin is filled in, ordinary PR CI automatically enables dual-encoding checks. Until then, CI explicitly reports that it covers only the old configuration baseline and must not be treated as ZIP release verification. Image records preserve the actually built `hosted_candidate`, original HEAD + dirty + source digest, and immutable image ID, explicitly marked as review candidates.

### Verification and end-to-end entry points

Implement `backend/scripts/check_observation_contract.py --openagents <checkout>` to pass actual producer output to the actual reader in CI without credentials or network, verifying gzip/ZIP, old handles, incorrect budgets, digests, issues, paths, ZIP negative cases, retry reuse, and legacy directory recovery; the script must not call an LLM. Retain the existing configuration contract checks.

Implement `backend/scripts/check_gitea_evidence_transport.py` as an explicit probe for a real user environment: read credentials only from env/private files, create only separate private repositories/Issues marked as probes, upload synthetic authorized evidence, invoke the actual publisher and OpenAgents prepare, and check session scope, digest, historical files, and read-only permissions; close the probe Issue at the end and output results without credentials or signed URLs. The probe must not consume real experiment feedback or silently create repositories during ordinary startups.

Verification must be performed separately on self-hosted Gitea, Gitea.com, E2B, and the actual container/proxy environment; public CI must not depend on private tokens, and real-user verification retains sanitized results separately. Negative cases include digest mismatches, incorrect issues, unauthorized scopes, multi-entry/path/encrypted ZIPs, size and time overruns, impersonating domains, API redirects, second redirects, object storage receiving authentication headers, old readers, and drifted frozen profiles. Positive cases must assert the actual evidence scope and files, rather than merely asserting the absence of exceptions.

Candidate verification was completed on 2026-09-29: actual producer → reader offline verification covered 7 files each for gzip/ZIP, 14 rejection categories, retry reuse, and legacy recovery; actual uploads/readbacks on both sites and `prepare` on the host, E2B, and inside the new image all obtained 7 files spanning two turns of history for the sole authorized session, with matching digests, content, and `0400` permissions, and no model calls. The hosted-service container was placed on an internal network and actually accessed Gitea.com/R2 through Squid; default rejection of the hosted site and rejection of impersonating domains/ports/IPs were all tested. Additional live tests covered the capability command for the new image ID and querying the reused container for the same run even when the local tag was absent. Temporary container/proxy networks and E2B probes have been cleaned up; synthetic private probe repositories and closed Issues are retained for audit. The old single-instance Gitea proxy retains its existing development-machine cache_peer; actual hosted-network verification used the per-experiment template.

## Drawbacks

The two repositories will temporarily maintain both gzip/ZIP and same-origin/hosted download paths, requiring shared contract cases to prevent implementation drift. Gitea.com's object storage domain is an external deployment fact; if it changes in the future, clients should explicitly reject it and update the support policy, rather than following arbitrary external links in pursuit of “always succeeding.”

Capability queries add one bounded startup check; they can only establish local code declarations and verified support, and cannot replace actual network, permission, and file round-trip verification.

## Rationale and alternatives

Choose an incremental extension at the existing transport boundary: preserve the gzip default and v1 content structure, adding ZIP, restricted downloads, and reader checks only for the new hosted path. Do not change evidence authorization or role responsibilities, or couple model event formats into the framework.

The first alternative is to require all users to self-host Gitea; this preserves the status quo but conflicts with an open-source user experience that requires no rented server. The second alternative is to switch everything to ZIP or upgrade to a new inner schema; this would impose unnecessary migration on existing self-hosted instances and old readers. The third alternative is to change the extension, skip preflight checks, or automatically follow redirects globally; these respectively fail to produce valid ZIPs, conceal actual failures, or expand credential/download boundaries. Adding a unified object storage service would introduce new accounts, permissions, and operations, exceeding the scope of this work.

## Prior art

The existing issue-authorized evidence workflow already provides version matching, content digests, upload readback, and Owner admission ordering; this group preserves these verified behaviors. The relevant baseline on 2026-09-29 was 35 passing tests in AHE-Beta and 64 in OpenAgents, successful cross-repository gzip transfer using actual functions, and rejection by the old reader of ZIP containing the same JSON; these are design evidence only and do not count as verification of the new feature.

[Gitea 1.22 configuration documentation](https://docs.gitea.com/1.22/administration/config-cheat-sheet/) describes attachment ALLOWED_TYPES, storage types, and SERVE_DIRECT; [Python zipfile documentation](https://docs.python.org/3/library/zipfile.html) describes ZIP members and the interfaces needed for bounded reads. Both explain external capabilities; compatibility with current sites remains subject to actual attachment probes.

## Unresolved questions

There are no design questions awaiting user input. Dual encoding, the strict hosted-download policy, actual reader checks, and reader-first release ordering have been approved and implemented. Subsequent commits/joint releases must enter the actual merged reader SHA and official image digest into the compatibility manifest and then retest; currently, explicitly labeled local candidate records are retained without fabricating remote pins.

## Future possibilities

Support for other hosted instances/S3/CDNs may be added incrementally as independent capability profiles; this group does not provide arbitrary-domain redirect configuration. A complete unified local/E2B startup experience and official benchmark scoring remain separate work and must not be claimed complete merely because the attachment path passes verification.

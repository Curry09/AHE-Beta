# Joint Release Guide

AHE-Beta and OpenAgents maintain their versions separately and record their compatibility in the [compatibility manifest](../backend/compatibility.json). A joint release should pin the source versions, dependencies, and runtime materials for both projects so users can install and run the same set of components; the version numbers of the two repositories do not need to match.

## Pinning Compatible Versions

Before release, check the following sources:

| Content | Configuration source |
| --- | --- |
| Controller and initial Harness | Release commit and `backend/harness_template/` |
| Compatible OpenAgents version | `backend/compatibility.json` and `source.openagents` explicitly specified in the experiment |
| NexAU | `pyproject.toml`, `uv.lock`, and the fixed Git commit in the compatibility manifest |
| Python, uv, Claude Code | `experiment_runtime` in the compatibility manifest and the actual runtime recipe |
| Task inputs, environment recipes, and images | Task materials manifest, SHA-256, and image digest |
| Independent evaluation materials | `evaluation/requirements.lock`, task provenance records, and runtime release package |

Experiment preparation uses OpenAgents' `reader_release_commit` from `execution_evidence`, or `reader_candidate_commit` if the release pin is unset. The `observation_transport` pins are the fallback when `execution_evidence` is absent. An explicit `source.openagents` can select another immutable commit; it must pass the same capability checks.

Candidate commits and official release commits should be clearly distinguished. When preparing an official joint release, write the verified compatible commits to the corresponding `reader_release_commit`, synchronize the related transport configuration, and rebuild and validate the runtime images. Use the manifest as the source of truth for versions, rather than copying commit values into tutorials where they can quickly become outdated.

## Release Checks

Complete the checks on the target release commit and record the results and scope in the release notes:

- Install dependencies from the lockfile and run the Python and independent evaluation checks. See the [contributor guide](../CONTRIBUTING.md) and [verification notes](VERIFICATION.md) for specific commands.
- Verify the configuration interface and evidence-reading capabilities of the compatible OpenAgents version, including gzip, ZIP, and execution evidence. The cross-repository CI check is in [.github/workflows/ci.yml](../.github/workflows/ci.yml).
- For the target runtime backend, verify materials preparation, user trials, requirements delivery, the next round of trials, stop/resume, and terminal-state collection. Record the model, runtime environment, commits from both repositories, and image identity alongside the verification results.
- Check the complete Git history and release assets for sensitive information, address any issues found, and rotate any exposed credentials. See the [third-party notices](../THIRD_PARTY.md) for materials provenance and licenses.
- Verify the source code, task materials, runtime, and images that users actually obtain, including checksums, download permissions, and installation commands.
- Check required CI statuses, the private vulnerability-reporting channel, and documentation links between the two repositories.

Code tests, evidence-transfer verification, and full model experiments should be recorded separately. Each check should state the actual environment, versions, and results used.

## Release Order

1. Merge and verify the compatible OpenAgents changes, then pin an installable source commit or release version.
2. Update the AHE-Beta compatibility manifest and lockfile, then complete cross-repository integration testing on the candidate release commit.
3. Build the required runtime, task materials, and images, and generate checksums and a materials manifest. Retain third-party licenses, copyright notices, and provenance statements for the release package.
4. Create a draft or prerelease, then verify downloading, installation, and execution from a clean environment by following the documentation.
5. Publish the official tag and Release. Link to each other from both sets of release notes and specify compatible versions, verification scope, and known limitations.

Published tags and pinned materials should not be replaced in place. Use a new version for corrected assets and retain the checksum information for the old version. If a candidate commit or materials change, repeat the affected checks.

## CI and Repository Access

Cross-repository CI needs to read OpenAgents. Public repositories can use the credentials provided by the workflow; if the compatible repository is still private, configure a read-only `OPENAGENTS_READ_TOKEN` in AHE-Beta’s Actions secrets. Do not put credentials in source code or workflow text.

`workflow_dispatch` in CI can pass a complete `observation_reader_commit` to verify another compatible commit; for an official release, the verified version must still be written back to the compatibility manifest. After changing a source pin, confirm that the actual runtime materials have been rebuilt and that preflight reads the same version.

## Manually Building Runtime Images

The unified experiment entry point obtains NexAU and OpenAgents from the frozen lockfile; no separate SDK source is needed. When calling `backend/deploy/vigil/build.sh` manually, however, you need to provide both OpenAgents and NexAU checkouts; when manually building the SWE runtime image, specify the SDK checkout using `NEXAU_SOURCE`.

These checkouts should match the commits in the release manifest. After building, record the image digest and verify the source and dependency versions inside the image in the actual runtime environment.

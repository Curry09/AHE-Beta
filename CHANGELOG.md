# Changelog

## Unreleased — open-source preparation

- Move the experiment compatibility pins into `backend/compatibility.json` and remove the release preparation directory.

- Remove the frontend application, published dashboard assets, and GitHub Pages deployment; retain CLI and read-only JSON observations.

- Align the project name with AHE-Beta and the architecture role with Architect across code, configuration, documentation and the dashboard.

- Add MIT licensing, contributor/security guidance and joint-release documentation.
- Declare the pinned NexAU runtime and compatibility dependencies.
- Align CI and local dependency installation with committed lockfiles.
- Add offline synthetic demo, cross-repository configuration check and frontend/evaluation CI.
- Restrict public snapshots to coarse allowlisted data; raw alerts and agent identifiers stay private.
- Require explicit credentials/service addresses in legacy deployment tools; bind local Gitea ports to loopback.

This is preparation on top of the recorded baseline, not a published release.

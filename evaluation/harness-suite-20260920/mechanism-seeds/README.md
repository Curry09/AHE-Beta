# Mechanism seed packages

This directory is the authoritative package for the four newly constructed
mechanism seeds M05, M07, M09 and M10. M01--M04 remain the authored historical
packages referenced by `task-manifest.json`; they are not copied or rewritten
here.

These are interactive task seeds, not benchmark records. Each package has:

- `public/`: the only task material mounted into the harness workspace;
- `user_context.md`: private user-side context for the simulator;
- `evaluation.json`: post-session evidence contract;
- `public/verify.sh`: a deterministic, offline check where appropriate.

The private context is not an oracle and is never mounted into the agent's
workspace. A mechanism only counts as exercised when the session trace shows
the corresponding behavior. A final repository state alone cannot prove
permission, memory, planning, or revision behavior.

Run the package checks without network access from this directory:

```bash
for task in M05 M07 M09 M10; do
  (cd "$task/public" && ./verify.sh)
done
```

The checks are intentionally independent of model providers, Harbor, Daytona,
and Docker image downloads. They are preparation smoke tests, not formal
experiment scores.

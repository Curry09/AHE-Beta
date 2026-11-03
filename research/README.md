# Historical research

New experiments use `backend/scripts/experiment.py` and the runnable definitions
in `examples/experiments/`. This directory contains frozen research records,
configuration templates and former implementations. It is not another supported
experiment entry point.

[简体中文](README.zh-CN.md)

The cleanup baseline is commit
`6d213f6f1383f6aed89111ddc83a076ba3f93976`. [inventory.json](inventory.json)
records original paths, destinations and source hashes. Public templates and
the corresponding frozen experiment configurations are distinct records.

To inspect or reproduce an older workflow, create a separate checkout of its
recorded source commit, install its dependencies and explicitly choose its
original frozen configuration. For the N1 pilot, use the original
`evaluation/harness-suite-20260920/configs/n1-e2b-20260922.json`; its launcher
default later pointed to the public v2 example. External task archives, cloud
snapshots and provider credentials remain prerequisites where documented.
Archiving a record does not establish that those external resources remain
available or that reproduction has been verified.

Archived source is kept as recorded. Its relative paths refer to the original
checkout, so do not execute it directly from this directory. Current tests and
lint exclude frozen source. Current held-out Harbor evaluation lives in
`evaluation/`; Harness adapters are in `evaluation/harness/`; developer tools live in `tools/dev/`.

Private raw sessions and experiment result bundles belong outside the source
repository. This cleanup does not manage or delete running cloud resources.

# Independent evaluation

`harness_bench/` contains held-out benchmark orchestration; `adapters/` contains
maintained benchmark integrations; `tests/` verifies them without claiming
official benchmark success.

Evolution experiments use `backend/scripts/experiment.py`. Historical pilot
workflows and results are indexed in [research](../research/README.md), rather
than presented as current experiment launchers.

The Harbor harness-v0 adapter requires explicit frozen materials:
`HARNESS_BASELINE_ARCHIVE` and `NEXAU_BASELINE_WHEEL`. Model settings are supplied
through its existing model/provider configuration. No developer home-directory
archive or wheel is assumed.

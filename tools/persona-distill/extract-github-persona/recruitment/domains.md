---
kind: domain-registry
scope: shared            # used by extract-github-persona, extract-stackoverflow-persona
vocab_source: ../../card-schema.md   # Single source of truth for the 14 D5.area controlled-vocabulary tokens (shared contract)
---

# Domain registry (anchor repos per controlled-vocab token)

**Why this file exists.** Domain is *not* a label you guess after producing a card — it is
a **property of where you harvested from**. You pick a target domain, harvest from that
domain's repos, and the `domain` field is then **derived from the repo's registry entry
(a FACT)**, not invented. This is what lets you *steer* coverage and kills the
"everything ends up `systems-runtime`/`data-eng`" mislabeling failure.

The 14 controlled-vocabulary tokens for `D5.area` are defined by the shared contract
[`../../card-schema.md`](../../card-schema.md). This file only maps each token to anchor
repos and disambiguation rules; it does not repeat the vocabulary. In this hub-and-spoke
structure, the contract is the single source of truth.

**How to specify a domain when searching:**
1. Choose the target domain token (e.g. you need to fill `dev-tooling`).
2. Pull its **anchor repos** below (or widen with the GitHub `topic:` / `language:`
   filters in the same row).
3. Harvest there (seeds: closed issue + fix PR; personas: issue reporters / PR authors).
4. Set `domain` = this row's token. **Never set a domain that isn't this repo's row.**
5. If a repo isn't listed, either add it here under the right token, or pick the nearest
   token — but the token MUST be one of the 14 in card-schema.md (`validate_card` enforces the vocab).

Anchors are Python-first because harbor reproducibility favors Python; JS/native rows are
honest about lower repro yield.

| domain token | anchor repos (harvest here) | GitHub discovery filter | repro note |
|---|---|---|---|
| `web-backend` | `django/django`, `pallets/flask`, `pallets/werkzeug`, `encode/django-rest-framework`, `fastapi/fastapi`, `aio-libs/aiohttp` | `topic:web-framework language:python` | easy |
| `web-frontend` | `facebook/react`, `vuejs/core`, `sveltejs/svelte`, `vitejs/vite` | `topic:frontend language:typescript` | harder (node/build) → often rubric/SO |
| `scientific-computing` | `numpy/numpy`, `scipy/scipy`, `sympy/sympy`, `astropy/astropy`, `pydata/xarray` | `topic:scientific-computing language:python` | easy–medium |
| `data-viz` | `matplotlib/matplotlib`, `mwaskom/seaborn`, `bokeh/bokeh`, `plotly/plotly.py` | `topic:plotting language:python` | easy (use Agg backend) |
| `ml-ai` | `scikit-learn/scikit-learn`, `huggingface/transformers`, `keras-team/keras` | `topic:machine-learning language:python` | medium (avoid GPU/big-weights seeds) |
| `data-analysis` | `pandas-dev/pandas`, `pola-rs/polars`, `apache/arrow (pyarrow)` | `topic:data-analysis language:python` | easy–medium |
| `dev-tooling` | `pytest-dev/pytest`, `pylint-dev/pylint`, `sphinx-doc/sphinx`, `pallets/click`, `fastapi/typer`, `python-attrs/attrs`, `pypa/packaging`, `more-itertools/more-itertools`, `psf/black`, `astral-sh/ruff` | `topic:developer-tools language:python` | easy (default home for CLI/lib/test/lint/packaging utils) |
| `data-eng` | `apache/airflow`, `dbt-labs/dbt-core`, `dagster-io/dagster`, `apache/beam` | `topic:data-engineering language:python` | medium (pin connectors; reject live-cloud) |
| `infra-devops` | `ansible/ansible`, `hashicorp/terraform`, `kubernetes/kubernetes`, `prometheus/prometheus` | `topic:devops` | medium–hard (prefer in-repo logic bugs) |
| `databases` | `sqlalchemy/sqlalchemy`, `psycopg/psycopg`, `redis/redis-py`, `mongodb/mongo-python-driver` | `topic:database language:python` | medium (containerize the DB) |
| `systems-runtime` | `python/cpython`, `cython/cython`, `rust-lang/cargo`, `llvm/llvm-project` | `topic:compiler OR topic:runtime` | medium–hard (build toolchain) |
| `security` | `pyca/cryptography`, `certbot/certbot`, `pyca/pyopenssl` | `topic:security language:python` | medium (no live certs/CA) |
| `mobile` | `flutter/flutter`, `facebook/react-native` | `topic:mobile` | hard (device/emulator) → usually SO/rubric |
| `cross-stack` | full-stack monorepos / framework metas; use **only** when a task genuinely spans tiers | — | varies |

## Disambiguation (the traps this batch hit)

Assign by **what the library *is*, not where it incidentally gets used**:

- A datetime / iterator / class-boilerplate / packaging utility → `dev-tooling`
  (e.g. `dateutil`, `more-itertools`, `attrs`, `packaging`). **Not** `systems-runtime`
  (that's compilers/runtimes/low-level) and **not** `data-eng` (that's pipelines/ETL).
- A templating engine (`jinja`) → `web-backend` (it renders responses/config), not `data-eng`.
- A schema/validation lib (`jsonschema`) → `web-backend` (API/payload validation) or
  `dev-tooling`, **not** `data-analysis` (that's pandas/EDA/notebooks).
- A CLI framework (`click`, `typer`) → `dev-tooling`. There is **no** `cli/utilities`
  token; `cli/...` is not in the vocab and `validate_card` rejects it.

Rule of thumb: if it's a general-purpose Python library/tool used across many app types,
it is almost always `dev-tooling` — do not inflate it into `systems-runtime` / `data-eng`
/ `data-analysis` to fake spread. Real spread comes from harvesting **different rows**,
not from relabeling one row.

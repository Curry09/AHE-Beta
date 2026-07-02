---
target: swe-bench
priority_domains: [web-backend, ml-ai, scientific-computing, data-viz, dev-tooling]
pools:
  github: repos          # consumed by extract-github-persona (expert/competent end)
  stackoverflow: tags    # consumed by extract-stackoverflow-persona (blind/surface end)
---

# Recruitment target: SWE-bench

SWE-bench tasks come from ~12 mature Python libraries. This profile is **multi-source**:
the GitHub skill mines the same domains from the repos below (expert/competent end), the
SO skill mines them from the tags below (blind/surface end). One profile, both ends of
D1, same domains.

## GitHub pool (extract-github-persona)

The people who **file issues and submit PRs** against these repos are domain-correct,
high-trace, and tend to pass the authenticity gate by construction.

| Priority domain | Recruit from (repos) | Notes |
|---|---|---|
| `web-backend` | `django/django`, `pallets/flask`, `psf/requests` | frameworks + HTTP client |
| `ml-ai` | `scikit-learn/scikit-learn` | **classical** ML, not LLM/DL |
| `scientific-computing` | `sympy/sympy`, `astropy/astropy`, `pydata/xarray` | symbolic math, domain science, n-d arrays |
| `data-viz` | `matplotlib/matplotlib`, `mwaskom/seaborn` | plotting / statistical viz |
| `dev-tooling` | `pytest-dev/pytest`, `pylint-dev/pylint`, `sphinx-doc/sphinx` | testing, linting, docs generators |

## Stack Overflow pool (extract-stackoverflow-persona)

Same domains, but pull **low-rep askers** under these tags to fill the blind/surface end.

| Priority domain | SO tags |
|---|---|
| `web-backend` | `django`, `flask`, `python-requests` |
| `ml-ai` | `scikit-learn` |
| `scientific-computing` | `sympy`, `numpy`, `astropy`, `python-xarray` |
| `data-viz` | `matplotlib`, `seaborn` |
| `dev-tooling` | `pytest`, `pylint`, `python-sphinx` |

## How to recruit (per repo)

1. `GET /search/issues?q=repo:{owner}/{repo}+type:issue&sort=created` → collect reporters.
2. Spread across the **contributor ladder** so D1 stays diverse within the domain:
   - core maintainer / frequent PR author → likely `competent`/`expert`
   - occasional contributor → `competent`/`surface`
   - drive-by bug reporter → `surface` (many will fall below the trace floor → expected, skip)
3. Follow each handle to their GitHub footprint and run **L0–L5 + the gate as usual**.

## Scope / cautions

- All Python, all library-maintenance flavored → naturally skews D5 toward these domains
  and D1 toward `competent`/`expert`. （注意：D2 验收 / D4 信任仍默认 injected——库维护并不
  等于本人陈述了验收线或对 agent 的信任，见本 skill 原则 4。）
- Do **not** try to source blind / vibe users here — that's the SO / forum source's
  job. This profile fills the *domain* axis, not the low end of D1.

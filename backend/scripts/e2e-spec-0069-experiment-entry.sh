#!/usr/bin/env bash
# Spec-0069/T6: offline contracts by default; paid live runs require explicit flags.
set -euo pipefail
cd "$(dirname "$0")/../.."
live=false
backend=
secrets_file=
runs_dir=.experiments
while (($#)); do
  case "$1" in
    --live) live=true; shift ;;
    --backend) backend="${2:?local or e2b required}"; shift 2 ;;
    --secrets-file) secrets_file="${2:?path required}"; shift 2 ;;
    --runs-dir) runs_dir="${2:?path required}"; shift 2 ;;
    *) echo "Usage: $0 [--live --backend local|e2b --secrets-file FILE] [--runs-dir DIR]" >&2; exit 2 ;;
  esac
done
if ! "$live"; then
  uv run --locked --extra experiments --extra dev pytest -q \
    backend/tests/test_experiment_config_v2.py \
    backend/tests/test_experiment_materials.py \
    backend/tests/test_experiment_engine.py \
    backend/tests/test_experiment_local_backend.py \
    backend/tests/test_experiment_e2b_backend.py \
    backend/tests/test_experiment_cli_v2.py \
    backend/tests/test_experiment_lifecycle_v2.py \
    backend/tests/test_experiment_public_examples.py
  exit
fi
[[ "$backend" == local || "$backend" == e2b ]] || { echo '--backend local|e2b required' >&2; exit 2; }
[[ -n "$secrets_file" ]] || { echo '--secrets-file FILE required' >&2; exit 2; }
config="examples/experiments/u1-$backend.json"
entry=(uv run --locked --extra experiments python backend/scripts/experiment.py --runs-dir "$runs_dir")
"${entry[@]}" check --config "$config" --offline
receipt=$("${entry[@]}" --json prepare --config "$config" --secrets-file "$secrets_file")
run_id=$(printf '%s' "$receipt" | uv run --locked python -c 'import json,sys; print(json.load(sys.stdin)["run_id"])')
printf 'Prepared live run: %s\n' "$run_id"
"${entry[@]}" run "$run_id"
printf 'Follow progress with: uv run --locked --extra experiments python backend/scripts/experiment.py --runs-dir %q logs %q --follow\n' "$runs_dir" "$run_id"
while true; do
  status=$("${entry[@]}" --json status "$run_id")
  state=$(printf '%s' "$status" | uv run --locked python -c 'import json,sys; print(json.load(sys.stdin)["experiment_state"])')
  printf 'Experiment state: %s\n' "$state"
  case "$state" in
    COMPLETED) "${entry[@]}" collect "$run_id"; break ;;
    FAILED|LOST|STOPPED) "${entry[@]}" collect "$run_id" || true; exit 1 ;;
  esac
  sleep 15
done
"${entry[@]}" status "$run_id"

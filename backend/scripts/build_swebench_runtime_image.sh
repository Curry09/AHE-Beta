#!/usr/bin/env bash
# Build a runnable, session-container seed from the immutable storage seed.
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/../.." && pwd)"
seed_image="${SWEBENCH_STORAGE_SEED_IMAGE:?Set the immutable storage seed image}"
runtime_image="${SWEBENCH_RUNTIME_SEED_IMAGE:?Set the output runtime image}"
nexau_source="${NEXAU_SOURCE:?Set NEXAU_SOURCE to a checkout of the locked hzhua/nexau commit}"
builder_python="${NEXAU_BUILD_PYTHON:-$repo_root/.venv/bin/python}"
build_context="$(mktemp -d /tmp/ahe-beta-runtime-image.XXXXXX)"
cleanup() { rm -rf -- "$build_context"; }
trap cleanup EXIT

docker image inspect "$seed_image" >/dev/null
test -f "$nexau_source/pyproject.toml"
test -x "$builder_python"
uv build --python "$builder_python" "$nexau_source" --wheel --out-dir "$build_context" >/dev/null
sdk_wheels=("$build_context"/nexau-*.whl)
test -f "${sdk_wheels[0]}"
cp "$repo_root/backend/deploy/swebench-seed/runtime.Dockerfile" "$build_context/runtime.Dockerfile"
cp "$repo_root/backend/scripts/prepare_swebench_runtime_tree.py" "$build_context/prepare_swebench_runtime_tree.py"
docker build \
  --file "$build_context/runtime.Dockerfile" \
  --build-arg "SEED_IMAGE=$seed_image" \
  --tag "$runtime_image" \
  "$build_context"

label="$(docker image inspect --format '{{ index .Config.Labels "org.auto-designer.seed-runtime" }}' "$runtime_image")"
test "$label" = 1
docker image inspect --format '{{.Id}}' "$runtime_image"

#!/usr/bin/env bash
# Spec-0033/T1: build vigil container image. Version pins for both OpenAgents and NexAU are determined by the incoming
# checkout; Docker named build context allows both repos to avoid copying to a common parent directory.
# Usage: ./build.sh <OpenAgents repo path> <NexAU repo path>
set -euo pipefail

OPENAGENTS_PATH="${1:?Usage: build.sh <OpenAgents-repo-path> <NexAU-repo-path>}"
NEXAU_PATH="${2:?Usage: build.sh <OpenAgents-repo-path> <NexAU-repo-path>}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIP_INDEX_URL="${VIGIL_PIP_INDEX_URL:-https://pypi.org/simple}"
IMAGE_TAG="${VIGIL_IMAGE_TAG:-ahe-beta-vigil:latest}"
CLAUDE_CODE_VERSION="${VIGIL_CLAUDE_CODE_VERSION:-2.1.261}"
OBSERVATION_PROFILE="${VIGIL_OBSERVATION_PROFILE:-}"
if [[ -n "$OBSERVATION_PROFILE" ]]; then
  [[ "$OBSERVATION_PROFILE" == "gitea-com-r2-v1" ]] || {
    echo "Unknown VIGIL_OBSERVATION_PROFILE" >&2; exit 1;
  }
  [[ -n "${VIGIL_IMAGE_TAG:-}" && "$IMAGE_TAG" == *:* && "$IMAGE_TAG" != *:latest ]] || {
    echo "Hosted evidence builds require an explicit VIGIL_IMAGE_TAG (latest is not allowed)" >&2; exit 1;
  }
  command -v python3 >/dev/null || { echo "Capability validation requires python3" >&2; exit 1; }
fi

test -f "$OPENAGENTS_PATH/pyproject.toml" || {
  echo "Not an OpenAgents repository (missing pyproject.toml): $OPENAGENTS_PATH" >&2
  exit 1
}
grep -q 'name = "openagents"' "$OPENAGENTS_PATH/pyproject.toml" || {
  echo "pyproject does not declare the openagents package: $OPENAGENTS_PATH" >&2
  exit 1
}

test -f "$NEXAU_PATH/pyproject.toml" || {
  echo "Not a NexAU repository (missing pyproject.toml): $NEXAU_PATH" >&2
  exit 1
}
grep -q 'name = "nexau"' "$NEXAU_PATH/pyproject.toml" || {
  echo "pyproject does not declare the nexau package: $NEXAU_PATH" >&2
  exit 1
}

build_args=(build \
  --build-context "nexau=$NEXAU_PATH" \
  --build-arg "PIP_INDEX_URL=$PIP_INDEX_URL" \
  --build-arg "CLAUDE_CODE_VERSION=$CLAUDE_CODE_VERSION" \
  --build-arg "HTTP_PROXY=${http_proxy:-${HTTP_PROXY:-}}" \
  --build-arg "HTTPS_PROXY=${https_proxy:-${HTTPS_PROXY:-}}" \
  --build-arg "NO_PROXY=${no_proxy:-${NO_PROXY:-}}" \
  -f "$HERE/Dockerfile" \
  -t "$IMAGE_TAG" \
  "$OPENAGENTS_PATH")
if [[ -z "$OBSERVATION_PROFILE" ]]; then
  docker "${build_args[@]}"
fi

# Spec-0070/T4: validate the immutable built image, never the host checkout.
# A record is optional and is only emitted after this offline command succeeds.
if [[ -n "$OBSERVATION_PROFILE" ]]; then
  python3 - "$IMAGE_TAG" "$OPENAGENTS_PATH" "$NEXAU_PATH" "${VIGIL_OBSERVATION_RECORD:-}" "${build_args[@]}" <<'PYCODE'
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

image_tag, oa_path, nexau_path, record_path = sys.argv[1:5]
def source_record(path):
    root = Path(path).resolve()
    def git(*args):
        return subprocess.check_output(["git", "-C", str(root), *args])
    paths = sorted(set(git("ls-files", "--cached", "--others", "--exclude-standard", "-z").split(b"\0")) - {b""})
    digest = hashlib.sha256()
    for relative in paths:
        item = root / os.fsdecode(relative)
        digest.update(relative + b"\0")
        if item.is_symlink():
            content, kind = os.fsencode(os.readlink(item)), b"symlink"
        elif item.is_file():
            content, kind = item.read_bytes(), b"executable" if item.stat().st_mode & 0o111 else b"file"
        else:
            content, kind = b"", b"missing"
        digest.update(kind + b"\0" + hashlib.sha256(content).digest())
    return {
        "commit": git("rev-parse", "HEAD").decode().strip(),
        "dirty": bool(git("status", "--porcelain")),
        "source_sha256": digest.hexdigest(),
        "digest_scope": "git-tracked-and-unignored-files-v1",
    }


source_before = {"openagents": source_record(oa_path), "nexau": source_record(nexau_path)}
subprocess.run(["docker", *sys.argv[5:]], check=True)
source_after = {"openagents": source_record(oa_path), "nexau": source_record(nexau_path)}
if source_before != source_after:
    raise SystemExit("Source changed during the build; retry. No validation record was written")
image_id = subprocess.check_output(
    ["docker", "image", "inspect", "--format", "{{.Id}}", image_tag], text=True,
).strip()
if not image_id.startswith("sha256:") or len(image_id) != 71:
    raise SystemExit("Could not obtain the actual image ID")
name = "observation-capabilities-" + uuid.uuid4().hex
try:
    with tempfile.TemporaryFile() as output:
        result = subprocess.run(
            ["docker", "run", "--rm", "--name", name, "--network", "none",
             "--env", "OPENAGENTS_NO_SELF_UPDATE=1", "--entrypoint", "openagents",
             image_id, "observation-capabilities", "--json"],
            stdout=output, stderr=subprocess.DEVNULL, timeout=10,
        )
        output.seek(0)
        raw = output.read(16_385)
    if result.returncode or len(raw) > 16_384:
        raise ValueError("reader command failed or exceeded output limit")
    capability = json.loads(raw)
    expected = {
        "schema": "openagents-observation-reader-capabilities-v1",
        "marker": "auto-designer:observation-evidence-v1",
        "encodings": ["gzip", "zip"],
        "zip_profile": "single-evidence-json-v1",
        "download_policies": ["same-origin-v1", "gitea-com-r2-v1"],
        "max_transfer_bytes": 4_000_000,
        "max_expanded_bytes": 24_000_000,
    }
    if not isinstance(capability, dict) or any(capability.get(k) != v for k, v in expected.items()):
        raise ValueError("reader capabilities do not satisfy the hosted profile")
except (ValueError, subprocess.SubprocessError):
    raise SystemExit("The built image failed offline hosted-evidence capability validation; no validation record was written") from None
finally:
    subprocess.run(["docker", "rm", "--force", name], stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, timeout=10, check=False)



record = {
    "schema": "observation-runtime-build-v1", "image_tag": image_tag, "image_id": image_id,
    **source_before,
    "capabilities": capability, "validation": "offline image capability command; network none",
    "deployment": "Not deployed; does not replace the historical runtime pin.",
}
if record_path:
    target = Path(record_path).resolve()
    # Do not silently overwrite a previously audited image record.
    with target.open("x", encoding="utf-8") as handle:
        json.dump(record, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
print("✓ Hosted-evidence reader capability validation passed: " + image_id)
PYCODE
fi
echo "✓ Image $IMAGE_TAG built (OpenAgents pin = $(git -C "$OPENAGENTS_PATH" rev-parse --short HEAD 2>/dev/null || echo 'not a Git checkout'), NexAU pin = $(git -C "$NEXAU_PATH" rev-parse --short HEAD 2>/dev/null || echo 'not a Git checkout'))"

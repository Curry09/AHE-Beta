"""Generate reproducibility records and one source archive per Harness, not per task."""

from __future__ import annotations

import hashlib
import io
import json
import random
import tarfile
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .benchmarks import configuration_profile
from .harbor.contracts import runtime_identity, runtime_source_files
from .harbor.tasks import resolve_case, verify_case
from .manifest import _assert_secret_free, digest_json

PACKAGE = Path(__file__).parent
ROOT = PACKAGE.parent
NATIVE = {
    "claude-code": ("claude-code", "2.1.119"),
    "meta-harness": ("meta-harness", "57fefdb2ff84af3fd81b69d67814acbe69bd0743"),
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def json_write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def source_files(source):
    result = {}
    for p in sorted(source.rglob("*")):
        relative = p.relative_to(source)
        if not p.is_file() or any(
            s in relative.parts
            for s in [
                ".git",
                ".gitea",
                "__pycache__",
                ".venv",
                "venv",
                ".pytest_cache",
                ".ruff_cache",
                "node_modules",
                "secrets",
            ]
        ):
            continue
        if (
            "docs/evidence/" in relative.as_posix()
            or any(part.startswith(".env") for part in relative.parts[:-1])
            or (p.name.startswith(".env") and p.name != ".env.example")
            or p.name in {"credentials.json", "hosts.yml", "settings.local.json"}
            or p.suffix.lower() in {".env", ".pem", ".key", ".p12", ".pfx", ".pyc", ".pyo"}
        ):
            continue
        if p.is_symlink():
            raise ValueError("Harness source must not contain linked files")
        result[relative.as_posix()] = p.read_bytes()
    if "entry.py" not in result:
        raise ValueError("Harness entry.py missing")
    return result


def freeze_harness(name, source, cache, runtime):
    files = source_files(source)
    source_hashes = {p: sha(b) for p, b in files.items()}
    # Runtime bootstrap/capture are framework-owned. The original entry is retained verbatim.
    files["_harness_entry.py"] = files.pop("entry.py")
    files["entry.py"] = (PACKAGE / "harness/runtime_bootstrap.py").read_bytes()
    files["fulltrace.py"] = (PACKAGE / "harness/fulltrace.py").read_bytes()
    identity = digest_json({p: sha(b) for p, b in files.items()})
    folder = cache / "materials" / name / identity
    archive = folder / "harness.tar.gz"
    if not archive.exists():
        folder.mkdir(parents=True, exist_ok=True)
        with tarfile.open(archive, "w:gz") as t:
            for p, b in sorted(files.items()):
                info = tarfile.TarInfo(p)
                info.size = len(b)
                info.mode = 0o644
                t.addfile(info, io.BytesIO(b))
        json_write(folder / "source-files.json", source_hashes)
    with tarfile.open(archive) as t:
        actual = {m.name: sha(t.extractfile(m).read()) for m in t if m.isfile()}
        assert actual == {p: sha(b) for p, b in files.items()}, "Generated archive changed"
    return dict(
        id=name,
        archive=str(archive),
        sha256=sha(archive.read_bytes()),
        revision="source-tree:" + digest_json(source_hashes),
        runtime=runtime,
        adapter="stdio-jsonl-v1",
        internal_call_timeout_sec=None,
        source_hashes=source_hashes,
    )


def runtime_descriptor():
    directory = PACKAGE / "_runtime"
    if not directory.is_dir():
        directory = ROOT / "runtime"
    expected = json.loads((directory / "manifest.json").read_text())
    for n, h in expected.items():
        if sha((directory / n).read_bytes()) != h:
            raise ValueError("Runtime asset changed: " + n)
    wheel = "nexau-0.4.1-py3-none-any.whl"
    return dict(
        runtime_wheel=str(directory / wheel),
        runtime_sha256=expected[wheel],
        runtime_lock=str(directory / "runtime.lock"),
        runtime_lock_sha256=expected["runtime.lock"],
        python_archive=str(directory / "python312.tar.gz"),
        python_sha256=expected["python312.tar.gz"],
    )


def prepare(config, download=True):
    config.validate_sources()
    cache = config.path("cache")
    runtime = runtime_descriptor()
    profile = configuration_profile(config.data["task_source"])
    ds, cases = profile.prepare_cases(config, download=download)
    for c in cases:
        verify_case(asdict(c))
    resolved = {f"{c.benchmark}/{c.task_id}": resolve_case(asdict(c)) for c in cases}
    harnesses = []
    for name in config.data["harnesses"]:
        if name in NATIVE:
            kind, version = NATIVE[name]
            if name == "meta-harness":
                source = config.path("harnesses") / "Meta-Harness"
                provenance = json.loads(
                    (PACKAGE / "harness/meta_artifact/provenance.json").read_text()
                )
                for relative, expected in provenance["upstream_files"].items():
                    original = source / relative
                    if not original.is_file() or sha(original.read_bytes()) != expected:
                        raise ValueError(
                            "Meta-Harness source differs from pinned revision: " + relative
                        )
                for original in source.glob("*.py"):
                    if original.name == "__init__.py":
                        continue
                    target = PACKAGE / "harness/meta_artifact" / original.name
                    data = original.read_bytes().replace(
                        b"from anthropic_caching import ",
                        b"from .anthropic_caching import ",
                    )
                    if not target.is_file() or target.read_bytes() != data:
                        raise ValueError(
                            "Meta-Harness source differs from pinned artifact: " + original.name
                        )
            harnesses.append(
                dict(
                    id=name,
                    kind="native",
                    agent=kind,
                    version=version,
                    process_runtime={k: runtime[k] for k in ["python_archive", "python_sha256"]},
                )
            )
        else:
            harnesses.append(freeze_harness(name, config.path("harnesses") / name, cache, runtime))
    return ds, cases, resolved, harnesses


def plan(config, download=True, new_run=False):
    ds, cases, resolved, harnesses = prepare(config, download)
    d = config.data
    actor = d["actor"]
    user = d["user"]
    interaction = dict(
        mode="simulated_user",
        policy="reply_then_followup_v1",
        user_model="openai/" + user["model"],
        persona="python-competent-feedback-v1",
    )
    trials = []
    for c in cases:
        for h in harnesses:
            for rep in range(1, d["execution"]["repetitions"] + 1):
                t = dict(
                    benchmark=c.benchmark,
                    task_id=c.task_id,
                    case_digest=c.digest,
                    harness=h["id"],
                    interaction="simulated_user" if user["enabled"] else "direct",
                    policy="reply_then_followup_v1" if user["enabled"] else "direct",
                    seed=None,
                    repetition=rep,
                    time_adaptation=d["execution"]["time_adaptation"] and h.get("kind") != "native",
                )
                t["trial_id"] = digest_json(t)[:24]
                trials.append(t)
    random.Random(17).shuffle(trials)
    body = dict(
        schema_version=2,
        suite=d["name"],
        framework_commit="standalone-unified-1.0.0",
        cases=[asdict(c) for c in cases],
        dataset=ds,
        harnesses=harnesses,
        harness_model="openai/" + actor["model"],
        interactions=[interaction],
        provider=dict(
            type="e2b",
            concurrency=d["execution"]["concurrency"],
            ephemeral=True,
            kwargs={},
        ),
        measurement=dict(repetitions=d["execution"]["repetitions"], scheduling_seed=17),
        resolved_cases=resolved,
        image_digests={},
        trials=trials,
        fallback_agent_timeout_seconds=1800,
        metadata=dict(
            evaluation_runtime=dict(
                actor=actor, user=user, judge=d["judge"], experience=d["experience"]
            ),
            time_adaptation=d["execution"]["time_adaptation"],
            automatic_score_retries=False,
            official_budgets_unchanged=True,
            configuration=config.data,
            experience_protocol="full-visible-dialogue-retrospective-v1",
        ),
    )
    body["executor_source_files"] = runtime_source_files()
    body["runtime_identity"] = runtime_identity()
    _assert_secret_free(body, "manifest")
    if new_run:
        body["new_run_nonce"] = uuid4().hex
    body["manifest_digest"] = digest_json(body)
    body["run_id"] = "hbench-" + body["manifest_digest"][:16]
    root = config.path("runs") / body["run_id"]
    root.mkdir(parents=True, exist_ok=True)
    existing = root / "manifest.json"
    if existing.exists():
        previous = json.loads(existing.read_text())
        assert previous["manifest_digest"] == body["manifest_digest"]
        body = previous
    else:
        body["created_at"] = datetime.now(UTC).isoformat()
        json_write(existing, body)
    return body, root

"""Export frozen AHE task recipes and cohort assignments as local Harbor tasks."""

from __future__ import annotations

import argparse
import hashlib
import json
import shlex
import shutil
import tempfile
from pathlib import Path

import yaml

from ahe_beta.experiment.config import load_task_package
from ahe_beta.experiment.task_environments.materials import fetch_material, materialize_input


def _json(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _command(spec, cwd):
    return (
        "(cd "
        + shlex.quote(spec.get("cwd", cwd))
        + " && timeout "
        + str(int(spec["timeout_seconds"]))
        + " "
        + shlex.join(spec["argv"])
        + ")"
    )


def _readiness(spec, cwd):
    command = _command(spec, cwd)
    return (
        f"end=$(( $(date +%s) + {int(spec['timeout_seconds'])} ))\n"
        f"until {command}; do\n"
        '  [ "$(date +%s)" -lt "$end" ] || exit 70\n  sleep 1\ndone\n'
    )


def _service_script(service, cwd):
    text = "#!/bin/sh\nset -eu\nmkdir -p /run/ahe-services\n"
    for dependency in service.get("depends_on", []):
        text += f"while [ ! -f /run/ahe-services/{dependency}.ready ]; do sleep 1; done\n"
    command = "env " + shlex.join([f"{k}={v}" for k, v in service.get("environment", {}).items()])
    command += " " + shlex.join(service["argv"])
    text += "cd " + shlex.quote(service.get("cwd", cwd)) + "\n"
    if service.get("mode") == "oneshot":
        text += f"timeout {int(service['timeout_seconds'])} {command}\n"
    else:
        text += (
            command + ' &\nchild=$!\necho "$child" > /run/ahe-services/' + service["id"] + ".pid\n"
        )
        text += _readiness(service["readiness"], service.get("cwd", cwd))
    text += f"touch /run/ahe-services/{service['id']}.ready\n"
    text += 'wait "$child"\n' if service.get("mode") != "oneshot" else "exec sleep infinity\n"
    return text


def export_task(package_path, *, output, cache, agent_seconds):
    package_path = Path(package_path).resolve()
    package = load_task_package(package_path)
    if package["schema_version"] != 3:
        raise ValueError("Hermit export currently requires the frozen container task format")
    env = package["environment"]
    agent_seconds = agent_seconds or package.get("execution", {}).get("budget_seconds", 7200)
    output = Path(output)
    if output.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".harbor-export-", dir=output.parent) as temporary:
        root = Path(temporary)
        instruction = (package_path.parent / package["instruction_file"]).read_text()
        _write(root / "instruction.md", instruction)
        build = root / "environment"
        build.mkdir()
        services = env.get("services", [])
        containers = {
            "main": {
                "image": env["image"],
                "cwd": env["workdir"],
                "user": env.get("user", "root"),
                "environment": env.get("variables", {}),
                "resources": env.get("resources", {}),
            }
        }
        containers.update({s["id"]: s for s in services if s["placement"] == "companion"})
        copies = {name: [] for name in containers}
        inventory = []
        for item in env.get("inputs", []):
            material = dict(item["material"])
            blob = fetch_material(material=material, cache=Path(cache))
            destination = build / "inputs" / item["id"]
            material["path"] = str(blob)
            materialize_input(material=material, destination=destination)
            source = destination / "input" if material["format"] == "file" else destination
            target = item["target"]
            container = "main" if item.get("placement", "task") == "task" else item["placement"]
            copies[container].append(
                "COPY " + json.dumps([source.relative_to(build).as_posix(), target]) + "\n"
            )
            inventory.append(
                {
                    "id": item["id"],
                    "sha256": material["sha256"],
                    "placement": container,
                    "target": target,
                }
            )
        for service in services:
            _write(build / f"service-{service['id']}.sh", _service_script(service, env["workdir"]))
        startup = "#!/bin/sh\nset -eu\nmkdir -p /run/ahe-services\nchmod 755 /run/ahe-services\n"
        if env.get("initialize"):
            startup += _command(env["initialize"], env["workdir"]) + "\n"
        for service in services:
            if service["placement"] == "task":
                startup += f"sh /opt/ahe/service-{service['id']}.sh > /run/ahe-services/{service['id']}.log 2>&1 &\n"
        for service in services:
            startup += f"while [ ! -f /run/ahe-services/{service['id']}.ready ]; do sleep 1; done\n"
        startup += _readiness(env["readiness"], env["workdir"])
        startup += "touch /run/ahe-services/task.ready\nexec sleep infinity\n"
        _write(build / "start-main.sh", startup)
        compose = {"services": {}, "volumes": {"ahe-services": {}}}
        for name, container in containers.items():
            filename = "Dockerfile" if name == "main" else f"Dockerfile.{name}"
            dockerfile = "FROM " + container["image"] + "\nUSER root\n"
            dockerfile += "".join(copies[name])
            for service in services:
                dockerfile += (
                    "COPY "
                    + json.dumps(
                        [f"service-{service['id']}.sh", f"/opt/ahe/service-{service['id']}.sh"]
                    )
                    + "\n"
                )
            dockerfile += "COPY start-main.sh /opt/ahe/start-main.sh\n"
            dockerfile += "WORKDIR " + container.get("cwd", "/") + "\n"
            if container.get("user"):
                dockerfile += "USER " + str(container["user"]) + "\n"
            _write(build / filename, dockerfile)
            row = {
                "build": {"context": ".", "dockerfile": filename},
                "entrypoint": [],
                "command": [
                    "sh",
                    "/opt/ahe/start-main.sh" if name == "main" else f"/opt/ahe/service-{name}.sh",
                ],
                "environment": container.get("environment", {}),
                "volumes": ["ahe-services:/run/ahe-services"],
            }
            if name == "main":
                row["networks"] = {"default": {"aliases": ["task"]}}
                if "ptrace" in env.get("capabilities", []):
                    row["cap_add"] = ["SYS_PTRACE"]
                    row["security_opt"] = ["seccomp=unconfined"]
            else:
                resources = container.get("resources", {})
                if resources.get("cpus"):
                    row["cpus"] = resources["cpus"]
                if resources.get("memory_mb"):
                    row["mem_limit"] = str(resources["memory_mb"]) + "m"
            compose["services"][name] = row
        _write(build / "docker-compose.yaml", yaml.safe_dump(compose, sort_keys=False))
        resources = env.get("resources", {})
        config = (
            f'schema_version = "1.4"\n\n[metadata]\nauthor_name = "AHE-Beta"\n'
            f"\n[agent]\ntimeout_sec = {agent_seconds}\n\n[verifier]\ntimeout_sec = 60\n"
            f"\n[environment]\nbuild_timeout_sec = 1800\nworkdir = {json.dumps(env['workdir'])}\n"
            f"cpus = {resources.get('cpus', 2)}\nmemory_mb = {resources.get('memory_mb', 2048)}\n"
            '\n[environment.healthcheck]\ncommand = "test -f /run/ahe-services/task.ready"\n'
            "interval_sec = 1\ntimeout_sec = 5\nretries = 1800\n"
        )
        _write(root / "task.toml", config)
        _write(
            root / "tests/test.sh",
            "#!/bin/sh\nset -eu\nmkdir -p /logs/verifier\n"
            "test -s /logs/agent/user-reward.txt\ncp /logs/agent/user-reward.txt /logs/verifier/reward.txt\n",
        )
        (root / "tests/test.sh").chmod(0o755)
        _write(
            root / "ahe-task.json",
            _json(
                {
                    "schema_version": 1,
                    "task": package,
                    "source_sha256": hashlib.sha256(package_path.read_bytes()).hexdigest(),
                    "materials": inventory,
                    "score_kind": "user_experience",
                }
            ),
        )
        shutil.copytree(root, output)
    return {
        "id": package["id"],
        "harbor_task": output.name,
        "instruction": instruction,
        "environment": env,
        "agent_seconds": agent_seconds,
        "artifacts": package.get("artifacts", {}).get("exports", []),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--task", type=Path)
    source.add_argument("--experiment", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--cache", required=True, type=Path)
    parser.add_argument(
        "--agent-seconds",
        type=int,
        help="Explicit task-budget override; otherwise keep each source task budget",
    )
    args = parser.parse_args()
    if args.agent_seconds is not None and args.agent_seconds <= 0:
        parser.error("--agent-seconds must be positive")
    if args.experiment:
        result = export_cohort(
            args.experiment, output=args.output, cache=args.cache, agent_seconds=args.agent_seconds
        )
    else:
        result = export_task(
            args.task, output=args.output, cache=args.cache, agent_seconds=args.agent_seconds
        )
    print(
        _json(
            {"path": str(args.output), "task_id": result.get("id"), "rounds": result.get("rounds")}
        )
    )


def export_cohort(config_path, *, output, cache, agent_seconds):
    output = Path(output).resolve()
    if output.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".cohort-", dir=output.parent) as temporary:
        stage = Path(temporary) / "cohort"
        manifest = _export_cohort(
            config_path, output=stage, cache=cache, agent_seconds=agent_seconds
        )
        stage.rename(output)
    return manifest


def _export_cohort(config_path, *, output, cache, agent_seconds):
    """Keep the native task/persona schedule; the last round is observation only."""
    from ahe_beta.experiment.config import config_hash, load_config_v2, load_task_packages
    from ahe_beta.experiment.workload import interaction_plan

    config = load_config_v2(config_path)
    packages = load_task_packages(config)
    cards = {
        row["id"]: row
        for row in json.loads(Path(config["workload"]["persona_library"]).read_text())
    }
    assignments = interaction_plan(config, packages)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    if (output / "tasks.jsonl").exists():
        raise FileExistsError(output / "tasks.jsonl")
    exported = {}
    for path, package in zip(config["workload"]["task_packages"], packages, strict=True):
        name = Path(path).parent.name.lower()
        exported[package["id"]] = export_task(
            path, output=output / "tasks" / name, cache=cache, agent_seconds=agent_seconds
        )
    rows, train, final = [], [], []
    packages_by_id = {p["id"]: p for p in packages}
    for round_no, pairs in enumerate(assignments, 1):
        for slot, (persona_id, task_id) in enumerate(pairs):
            row = exported[task_id]
            package = packages_by_id[task_id]
            digest = config_hash(data={"package": package, "instruction": row["instruction"]})
            binding = {
                "task_id": task_id,
                "task_digest": digest,
                "task_kind": package["kind"],
                "interaction": package["interaction"],
                "round": round_no,
                "slot": slot,
                "persona": cards[persona_id],
                "environment": row["environment"],
            }
            binding["scenario"] = {
                "description": row["instruction"],
                "workspace": {
                    "kind": "external",
                    "params": {
                        "task_id": task_id,
                        "task_digest": digest,
                        "task_kind": package["kind"],
                        "interaction": package["interaction"],
                        "evaluation_artifacts": row["artifacts"],
                        "execution": {
                            "task_budget_seconds": row["agent_seconds"],
                            "budget_source": "operator_quota",
                        },
                    },
                },
            }
            identifier = f"r{round_no:02}-s{slot:02}-{row['harbor_task']}"
            rows.append(
                {
                    "id": identifier,
                    "harbor_task": row["harbor_task"],
                    "instruction": row["instruction"],
                    "agent_timeout_sec": row["agent_seconds"],
                    "verifier_timeout_sec": 60,
                    "build_timeout_sec": 1800,
                    "ahe_session": binding,
                }
            )
            (final if round_no == len(assignments) else train).append(identifier)
    _write(
        output / "tasks.jsonl", "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    )
    _write(output / "train.txt", "\n".join(train) + "\n")
    _write(output / "final-round.txt", "\n".join(final) + "\n")
    manifest = {
        "schema_version": 1,
        "source_config_sha256": hashlib.sha256(Path(config_path).read_bytes()).hexdigest(),
        "rounds": len(assignments),
        "sessions_per_round": config["rounds"]["sessions_per_round"],
        "training_rounds": len(assignments) - 1,
        "final_round": len(assignments),
        "final_round_kind": "same-cohort observation, not held-out evaluation",
        "agent_seconds": agent_seconds,
        "roles": config["roles"],
        "models": config["models"],
        "source_runtime": config["runtime"],
        "target_runtime": "local-harbor-docker",
        "max_parallel_users": config["rounds"]["max_parallel_users"],
    }
    _write(output / "cohort.json", _json(manifest))
    return manifest


if __name__ == "__main__":
    main()

"""Map GSO's four timing CPUs into the sandbox's allowed host CPU set.

Official tests remain unchanged. Only a verifier-local taskset launcher maps
the literal ``-c 0-3`` when those host CPU numbers are outside its cpuset.
Baseline, candidate and oracle all use the same four logical host CPU IDs.
"""

import hashlib
import json
import shlex

from evaluation.environments.files import write_bytes


def launcher_source(cpus):
    if (
        len(cpus) != 4
        or len(set(cpus)) != 4
        or any(not isinstance(cpu, int) or isinstance(cpu, bool) or cpu < 0 for cpu in cpus)
    ):
        raise ValueError("Expected four distinct nonnegative host CPU IDs")
    selected = ",".join(map(str, cpus))
    return (
        '#!/bin/sh\nif [ "$#" -ge 2 ] && [ "$1" = "-c" ] && [ "$2" = "0-3" ]; then\n'
        "  shift 2\n"
        f'  exec /usr/bin/taskset -c {selected} "$@"\n'
        'fi\nexec /usr/bin/taskset "$@"\n'
    )


async def configure(environment, directory):
    script = (
        "import os,json,hashlib,pathlib;print(json.dumps({"
        "'allowed': sorted(os.sched_getaffinity(0)), 'path': os.environ['PATH'],"
        "'official_eval_sha256': hashlib.sha256(pathlib.Path('/tests/eval.sh').read_bytes()).hexdigest()}))"
    )
    result = await environment.exec(
        "/usr/bin/python3 -c " + shlex.quote(script), timeout_sec=30, user="root"
    )
    if result.return_code:
        raise RuntimeError("Cannot inspect the GSO verifier CPU affinity")
    evidence = json.loads(result.stdout)
    allowed = evidence["allowed"]
    selected = [0, 1, 2, 3] if set(range(4)).issubset(allowed) else allowed[:4]
    source = launcher_source(selected)
    runtime_path = "/opt/harbor-index-affinity/bin"
    path = runtime_path + ":" + evidence["path"]
    result = await environment.exec("mkdir -p " + runtime_path, user="root")
    if result.return_code:
        raise RuntimeError("Cannot create verifier-local affinity launcher")
    await write_bytes(environment, runtime_path + "/taskset", source)
    result = await environment.exec("chmod 755 " + runtime_path + "/taskset", user="root")
    if result.return_code:
        raise RuntimeError("Cannot enable verifier-local affinity launcher")
    # Probe the exact launcher resolution and verify the four pinned CPUs.
    check = "import os,json;print(json.dumps(sorted(os.sched_getaffinity(0))))"
    result = await environment.exec(
        "taskset -c 0-3 /usr/bin/python3 -c " + shlex.quote(check),
        env={"PATH": path},
        timeout_sec=30,
        user="root",
    )
    if result.return_code or json.loads(result.stdout) != selected:
        raise RuntimeError("GSO verifier cannot pin its four timing CPUs")
    evidence.update(
        selected_four_cpus=selected,
        requested_logical_cpus=[0, 1, 2, 3],
        physical_cpu_ids_remapped=selected != [0, 1, 2, 3],
        launcher_sha256=hashlib.sha256(source.encode()).hexdigest(),
        taskset_launcher=runtime_path + "/taskset",
    )
    (directory / f"{environment.session_id}-gso-affinity.json").write_text(
        json.dumps(evidence, indent=2)
    )
    return path

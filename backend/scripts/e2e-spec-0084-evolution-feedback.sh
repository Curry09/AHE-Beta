#!/usr/bin/env bash
# Spec-0084/T6: offline contracts, honest example generation and real verifier controls.
set -euo pipefail
EVOLUTION_REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$EVOLUTION_REPO_ROOT"
export PYTHONPATH="$EVOLUTION_REPO_ROOT/backend${PYTHONPATH:+:$PYTHONPATH}"
EVOLUTION_PYTHON="${EVOLUTION_PYTHON:-$EVOLUTION_REPO_ROOT/.venv/bin/python}"
if [[ ${1:-} == --help ]]; then
  cat <<'HELP'
Usage:
  e2e-spec-0084-evolution-feedback.sh
  e2e-spec-0084-evolution-feedback.sh --prepare-example DIR --backend local|e2b --grader-image IMAGE@sha256:DIGEST
  e2e-spec-0084-evolution-feedback.sh --grader-controls DIR
Default runs offline contracts only. Preparation generates a private Ed25519 key,
private grader and an enabled configuration with actual hashes; it starts no run.
--grader-controls executes positive/negative operator controls through the existing
Docker grading service. These controls are not model-driven Harness results.
Use experiment.py check/prepare/run and assessment-worker for a real backend canary.
EVOLUTION_PYTHON may select an existing installed environment.
HELP
  exit 0
fi
if [[ ! -x "$EVOLUTION_PYTHON" ]]; then
  echo 'Install dependencies: uv sync --locked --extra experiments --extra evaluation --extra dev' >&2
  exit 1
fi
if [[ $# -eq 0 ]]; then
  exec "$EVOLUTION_PYTHON" -m pytest -q \
    backend/tests/test_execution_contract.py \
    backend/tests/harness/test_seed_execution_contract.py \
    backend/tests/harness/test_launcher_budget.py \
    backend/tests/test_experiment_model_limits.py \
    backend/tests/user/test_direct_session.py \
    backend/tests/user/sim/test_feedback.py \
    backend/tests/demand/test_delivery_evidence.py \
    backend/tests/test_experiment_assessment_worker.py \
    backend/tests/test_evolution_feedback_e2e.py
fi
"$EVOLUTION_PYTHON" - "$EVOLUTION_REPO_ROOT" "$@" <<'PY'
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from auto_designer.evaluation.adapters.container import IMMUTABLE_IMAGE
from auto_designer.evaluation.service import build_request, evaluate_request
from auto_designer.experiment.config import load_config_v2, load_task_package
from auto_designer.experiment.grading_inputs import load_grading_plan, read_material

repo = Path(sys.argv[1])
parser = argparse.ArgumentParser()
mode = parser.add_mutually_exclusive_group(required=True)
mode.add_argument('--prepare-example', type=Path)
mode.add_argument('--grader-controls', type=Path)
parser.add_argument('--backend', choices=('local', 'e2b'))
parser.add_argument('--grader-image')
args = parser.parse_args(sys.argv[2:])


def digest(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


if args.prepare_example:
    if args.backend is None or args.grader_image is None:
        parser.error('--prepare-example requires --backend and --grader-image')
    if not IMMUTABLE_IMAGE.fullmatch(args.grader_image):
        parser.error('--grader-image must be an immutable image digest; resolve a local/pulled image first')
    root = args.prepare_example.expanduser().absolute()
    if root.exists() or any(parent.is_symlink() for parent in root.parents):
        parser.error('output directory must be new and have no symlink parents')
    root.mkdir(parents=True, mode=0o700)
    public = root / 'public/task'
    source = public / 'source'
    source.mkdir(parents=True)
    private = root / 'private'
    private.mkdir(mode=0o700)
    write_json(source / 'input.json', [{'units': 3, 'unit_price': 4}, {'units': 5, 'unit_price': 6}])
    (source / 'README.md').write_text('Synthetic order summary task; Python standard library only.\n')
    (public / 'instruction.md').write_text(
        'Read input.json in the project root. Compute the sum of units * unit_price across all rows. '
        'Create answer.json with exactly two integer fields: total (the computed sum) and '
        'row_count (the number of rows). Verify your output before finishing.\n'
    )
    (public / 'requirements.lock').write_text('# Standard library only; no third-party dependencies.\n')
    (public / 'setup.sh').write_text(
        '#!/usr/bin/env bash\nset -euo pipefail\n'
        ': "${TASK_ROOT:?}" "${TASK_PYTHON:?}" "${VIRTUAL_ENV:?}" "${UV_BIN:?}"\n'
        'cd "$TASK_ROOT"\n"$UV_BIN" venv --allow-existing --python "$TASK_PYTHON" "$VIRTUAL_ENV"\n'
        '"$VIRTUAL_ENV/bin/python" -c "import json; json.load(open(\'input.json\'))"\n'
    )
    (public / 'setup.sh').chmod(0o755)
    task = {
        'schema_version': 2, 'kind': 'ordinary', 'id': 'feedback-artifact-canary',
        'instruction_file': 'instruction.md', 'source': {'kind': 'local', 'path': 'source'},
        'setup': {'script': 'setup.sh', 'requirements_lock': 'requirements.lock'},
        'interaction': 'direct', 'not_in_benchmark': True,
        'execution': {'budget_seconds': 600, 'budget_source': 'operator_quota',
                      'quota_override_reason': 'Resource-bounded integration canary',
                      'public_deliverables': ['answer.json'],
                      'public_acceptance': ['Correct integer total and row_count from input.json']},
        'artifacts': {'version': 1, 'exports': [{'id': 'answer', 'source': 'workspace',
            'path': 'answer.json', 'content_type': 'application/json', 'required': True, 'max_bytes': 65536}]},
    }
    write_json(public / 'task.json', task)
    script = (
        'import json, sys\nfrom pathlib import Path\n'
        'try:\n    value = json.loads(Path(sys.argv[1]).read_text())\n'
        '    passed = (isinstance(value, dict) and set(value) == {"total", "row_count"}'
        ' and type(value["total"]) is int and type(value["row_count"]) is int'
        ' and value["total"] == 42 and value["row_count"] == 2)\n'
        'except (ValueError, TypeError, OSError):\n    passed = False\n'
        'Path(sys.argv[2]).write_text(json.dumps({"passed": passed}))\n'
    )
    (private / 'verifier.py').write_text(script)
    plan = {'schema_version': 1,
        'materials': {'verifier': {'path': 'verifier.py', 'sha256': digest(script.encode())}},
        'graders': [{'adapter': 'custom', 'contract_version': 1, 'task_ids': [task['id']],
            'inputs': {'script': 'verifier'}, 'timeout_seconds': 120,
            'config': {'image': args.grader_image,
                'argv': ['python', '/grader/script.py', '/inputs/answer.json', '/logs/verifier/result.json'],
                'artifact_map': {'answer': '/inputs/answer.json'}}}]}
    write_json(private / 'grading-plan.json', plan)
    key = Ed25519PrivateKey.generate()
    key_path = private / 'worker.key'
    descriptor = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'wb') as handle:
        handle.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    public_raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    (private / 'worker.pub').write_bytes(key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    definition = json.loads((repo / f'examples/experiments/evolution-feedback-{args.backend}.json').read_text())
    definition['workload'] = {'kind': 'ordinary', 'task_package': 'public/task/task.json',
        'persona_library': str(repo / 'examples/personas/u1.json'), 'persona_ids': ['sr-15-swyx']}
    definition['evaluation'] = {'session_grading': {'plan_sha256': digest((private / 'grading-plan.json').read_bytes()),
        'worker_key_sha256': digest(public_raw), 'runner': 'external'}}
    write_json(root / 'experiment.json', definition)
    controls = []
    for name, answer, expected in (('positive', {'total': 42, 'row_count': 2}, True),
                                   ('negative', {'total': 41, 'row_count': 2}, False)):
        path = private / f'{name}.json'
        write_json(path, answer)
        controls.append({'name': name, 'path': path.name, 'sha256': digest(path.read_bytes()), 'expected_passed': expected})
    write_json(private / 'controls.json', controls)
    load_config_v2(root / 'experiment.json')
    load_task_package(public / 'task.json')
    load_grading_plan(private / 'grading-plan.json')
    print(json.dumps({'config': str(root / 'experiment.json'), 'grading_plan': str(private / 'grading-plan.json'),
                      'public_key': str(private / 'worker.pub'), 'signing_key': str(key_path),
                      'controls': str(private / 'controls.json'), 'backend_started': False}))
else:
    if args.backend or args.grader_image:
        parser.error('--grader-controls uses the already frozen generated material')
    root = args.grader_controls.expanduser().absolute()
    private = root / 'private'
    config = load_config_v2(root / 'experiment.json')
    plan = load_grading_plan(private / 'grading-plan.json')
    if plan.digest != config['evaluation']['session_grading']['plan_sha256']:
        raise ValueError('Grader plan differs from the generated configuration')
    package = load_task_package(root / 'public/task/task.json')
    task = {'id': package['id'], 'kind': package['kind'], 'package': package,
            'digest': digest(json.dumps(package, sort_keys=True).encode())}
    controls = json.loads((private / 'controls.json').read_text())
    if {row['name'] for row in controls} != {'positive', 'negative'}:
        raise ValueError('Expected positive and negative controls')
    results_root = root / 'verifier-controls'
    results_root.mkdir(mode=0o700)
    rows = []
    for control in controls:
        if control['path'] not in {'positive.json', 'negative.json'}:
            raise ValueError('Control must be one generated private JSON file')
        path = private / control['path']
        payload = read_material(path, control['sha256'])
        request = build_request(task=task, session={'session_id': 'control-' + control['name']},
            outputs={'answer': {'path': str(path), 'sha256': digest(payload), 'bytes': len(payload),
                               'source': 'workspace', 'payload': payload}}, plan=plan,
            selection=plan.selections({package['id']})[package['id']])
        result = evaluate_request(request, results_root / control['name'])
        rows.append({'name': control['name'], 'expected_passed': control['expected_passed'], 'result': result})
        write_json(results_root / 'summary.json', {'scope': 'operator verifier controls, not Harness trials', 'results': rows, 'complete': False})
        if result['status'] != 'completed' or result['passed'] is not control['expected_passed']:
            raise RuntimeError(f"Control {control['name']} did not produce the expected result: {result.get('status')}")
    write_json(results_root / 'summary.json', {'scope': 'operator verifier controls, not Harness trials', 'results': rows, 'complete': True})
    print(json.dumps({'complete': True, 'scope': 'operator verifier controls, not Harness trials', 'receipt': str(results_root / 'summary.json')}))
PY

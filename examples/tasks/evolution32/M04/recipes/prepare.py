"""Restore the pinned source and original public brief; do not solve the task."""

from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import sys

from initialize import initialize


root = Path('/app/repo')
inputs = Path('/opt/task-inputs')
revision = '2e99cce10766c16c08aaf5c1fef8e6d17b857171'
initialize(bundle=inputs/'initial.bundle', revision=revision, workspace=root, overlays=[])
public = inputs/'public/M04/public'
shutil.copy2(public/'TASK.md', root/'TASK.md')
shutil.copytree(public/'case', root/'case')
reference = inputs/'reference/M04/reference/docs/source/configuration'
materials = root/'task_materials'
materials.mkdir()
shutil.copytree(reference, materials/'reference')
version = subprocess.check_output(['sqlfluff', '--version'], text=True).strip()
assert version.endswith('3.4.0'), version
record = {
    'source_revision': revision,
    'tool_version': version,
    'environment_origin': 'New task environment reconstruction; original SQLFluff version was not preserved',
    'source_origin': 'Exact upstream commit named in the original case/SOURCES.md',
    'python': sys.version,
    'cloud_database_credentials': 'not provided, as required by the original commission',
}
(materials/'environment.json').write_text(json.dumps(record, ensure_ascii=False, indent=2)+'\n')
with (root/'.git/info/exclude').open('a') as stream:
    stream.write('\n/TASK.md\n/case/\n/task_materials/\n/.venv/\n/reports/.collected-pilot.tar.gz\n')
inventory = json.loads((root/'case/repository-inventory.json').read_text())
assert inventory['revision'] == revision
actual = sorted(str(path.relative_to(root)) for path in root.rglob('*.sql'))
assert actual == sorted(inventory['sql_files']) and len(actual) == 69
print(json.dumps({'source_revision': revision, 'sql_files': len(actual), 'tool_version': version}))

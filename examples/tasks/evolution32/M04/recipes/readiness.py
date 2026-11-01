"""Validate the task's actual inputs and tools before the Actor starts."""

from pathlib import Path
import json
import subprocess


root = Path('/app/repo')
revision = '2e99cce10766c16c08aaf5c1fef8e6d17b857171'
for relative in ['TASK.md', 'case/SOURCES.md', 'case/repository-inventory.json',
                 'case/team-constraints.md', 'README.md', 'dbt_project.yml', 'packages.yml',
                 'models', 'macros', 'integration_tests', 'task_materials/reference',
                 'task_materials/environment.json']:
    assert (root/relative).exists(), relative
assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip() == revision
assert not subprocess.check_output(['git', 'status', '--porcelain'], cwd=root, text=True).strip()
inventory = json.loads((root/'case/repository-inventory.json').read_text())
assert sorted(str(p.relative_to(root)) for p in root.rglob('*.sql')) == sorted(inventory['sql_files'])
assert subprocess.check_output(['sqlfluff', '--version'], text=True).strip().endswith('3.4.0')
assert not (root/'reports').exists(), 'A previous solution was included in the initial task'
print(json.dumps({'ready': True, 'source_revision': revision, 'sql_file_count': 69,
                  'sqlfluff_version': '3.4.0', 'preexisting_solution': False}))

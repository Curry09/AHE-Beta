"""Regression tests for interrupted runs and stable observation snapshots."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest


def load(name):
    path = Path(__file__).parents[1] / 'harness-suite-20260920' / (name + '.py')
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sandbox(exit_code='', running=True, malformed=False):
    ledger = {'round': 1, 'revision': 71, 'padding': 'x' * 300_000,
              'rounds': {'1': {'stages': {'users': {'status': 'completed'},
                                         'triage': {'status': 'running'}}}}}
    def read(path, **kwargs):
        if path.endswith('/recovery.json'):
            return 'invalid' if malformed else json.dumps(ledger)
        if path.endswith('/run.json'):
            return json.dumps({'running': running, 'round': 1, 'total_rounds': 5})
        if path.endswith('/exit_code'):
            return exit_code
        return '{}'
    return SimpleNamespace(files=SimpleNamespace(read=read), commands=SimpleNamespace(
        run=lambda cmd, **kw: SimpleNamespace(stdout='22 openagents vigil --parallel 4' if cmd.startswith('ps') else '')))


def test_large_json_not_truncated():
    relay = load('sync_status_vps')
    value, _, _ = relay.snapshot(sandbox(), 'test', 'sb')
    assert value['recovery_revision'] == 71
    assert value['phase'] == 'triage'
    assert value['components'][0]['state'] == 'finished'
    assert value['components'][1]['state'] == 'running'


@pytest.mark.parametrize('exit_code', ['', '1'])
def test_stopped_controller_never_means_success(exit_code):
    relay = load('sync_status_vps')
    value, _, _ = relay.snapshot(sandbox(exit_code=exit_code, running=False), 'test', 'sb')
    assert value['state'] == 'controller_exited'
    if exit_code:
        assert value['components'][1]['state'] == 'interrupted'
        assert value['components'][-1]['state'] == 'retained'
        assert value['components'][-1]['process_running'] is True


def test_failed_read_does_not_publish_empty_progress():
    relay = load('sync_status_vps')
    with pytest.raises(ValueError, match='retaining'):
        relay.snapshot(sandbox(malformed=True), 'test', 'sb')


def test_dashboard_order_stable_and_keeps_unreadable_snapshot(tmp_path):
    dashboard = load('vps_status_dashboard')
    dashboard.ROOT = tmp_path
    for run_id, stamp in [('20260101-a', 'z'), ('20260102-b', 'a')]:
        directory = tmp_path / run_id
        directory.mkdir()
        (directory / 'status.json').write_text(json.dumps({'run_id': run_id, 'updated_at': stamp}))
    assert [r['run_id'] for r in dashboard._runs()] == ['20260102-b', '20260101-a']
    (tmp_path / '20260101-a/status.json').write_text('{')
    assert [r['run_id'] for r in dashboard._runs()] == ['20260102-b', '20260101-a']


def test_atomic_status_publish(tmp_path):
    relay = load('sync_status_vps')
    ask = tmp_path / 'askpass'
    ask.touch()
    calls = []
    def run(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=0)
    with patch.object(relay, '_ssh_env', return_value=({}, ask)), patch.object(relay.subprocess, 'run', side_effect=run):
        assert relay.push(tmp_path, 'host', 'redacted', '/srv/hse-status', 'run')
    assert '/.status-' in calls[1][-1]
    assert calls[2][-1].startswith('mv -- ')
    assert calls[2][-1].endswith('/run/status.json')


def test_public_mode_filters_raw_logs():
    dashboard = load('vps_status_dashboard')
    result = dashboard.public_status({'run_id': 'test', 'log_tail': 'secret', 'events': ['secret'],
                                      'sandbox_id': 'private'})
    assert 'secret' not in json.dumps(result)
    assert 'sandbox_id' not in result

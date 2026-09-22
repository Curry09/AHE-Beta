import importlib.util
import json
from pathlib import Path
import unittest


SUITE = Path(__file__).resolve().parents[1] / 'harness-suite-20260920'


def module(name):
    spec = importlib.util.spec_from_file_location(name, SUITE / (name + '.py'))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class ProposalProgressTest(unittest.TestCase):
    def test_admission_dedup_and_real_activity(self):
        relay = module('sync_status_vps')
        current = {'admitted_issue_ids': [5, 6, 7, 7], 'stages': {'delivery_wait': {'units': {
            'a': {'input': {'issue': 5}, 'status': 'completed'},
            'b': {'input': {'issue': 6}, 'status': 'running'},
            'c': {'input': {'issue': 7}, 'status': 'running'},
        }}}}
        events = [
            {'issue': 6, 'phase': 'solve', 'at': '2026-01-01T00:00:00Z'},
            {'issue': 6, 'phase': 'in-flight', 'pr': 10, 'at': '2026-01-01T01:00:00Z'},
            {'issue': 7, 'phase': 'ready', 'pr': 9, 'at': '2026-01-01T01:00:00Z'},
            {'issue': 8, 'phase': 'in-flight', 'at': '2026-01-01T01:00:00Z'},
        ]
        value = relay.proposal_progress(current, {}, 'partial\n' + '\n'.join(map(json.dumps, events)))
        self.assertEqual((value['admitted'], value['completed'], value['processing'], value['ready']), (3, 1, 1, 1))
        self.assertEqual(value['items'][1]['last_action'], 'solve')
        self.assertEqual(value['items'][1]['pr'], 10)

    def test_missing_observation_is_not_running(self):
        relay = module('sync_status_vps')
        current = {'admitted_issue_ids': [1]}
        self.assertEqual(relay.proposal_progress(current, {}, '')['unknown'], 1)
        value = relay.proposal_progress(current, {'runs': {'1': {'status': 'done'}}}, '')
        self.assertEqual(value['awaiting_confirmation'], 1)
        self.assertEqual(value['completed'], 0)

    def test_public_payload_never_includes_proposal_bodies(self):
        dashboard = module('vps_status_dashboard')
        value = dashboard.public_status({'proposals': {
            'admitted': 1, 'secret': 'sensitive',
            'items': [{'issue': 1, 'state': 'ready', 'body': 'sensitive'}],
        }})
        self.assertNotIn('sensitive', json.dumps(value))

    def test_done_overrides_old_inflight_observation(self):
        relay = module('sync_status_vps')
        value = relay.proposal_progress(
            {'admitted_issue_ids': [6]},
            {'runs': {'6': {'status': 'done', 'pr_number': 10}}},
            json.dumps({'issue': 6, 'phase': 'in-flight', 'at': '2026-01-01T00:00:00Z'}),
        )
        self.assertEqual(value['awaiting_confirmation'], 1)
        self.assertEqual(value['processing'], 0)

    def test_worker_review_phase_is_not_unknown(self):
        relay = module('sync_status_vps')
        for phase in ('solve', 'rebase', 'fix-ci', 'e2e', 'review-or-fix', 'merge', 'reply'):
            value = relay.proposal_progress({'admitted_issue_ids': [7]}, {},
                json.dumps({'issue': 7, 'phase': phase, 'at': '2026-01-01T00:00:00Z'}))
            self.assertEqual(value['processing'], 1, phase)
            self.assertEqual(value['unknown'], 0, phase)


if __name__ == '__main__':
    unittest.main()

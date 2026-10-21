import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('guard', Path(__file__).resolve().parents[2] / '.docker/upstream/guard.py')
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class GuardTest(unittest.TestCase):
    def setUp(self):
        self.node = {'name': 'approved', 'type': 'anytls', 'password': 'test-only'}
        self.approved = [{'key': 'U01', 'source_name': 'approved', 'source_sha256': guard.fingerprint(self.node),
                          'backend_id': 359, 'public_id': 360}]
        self.usage = {'expire': 10000, 'total': 1000, 'upload': 1, 'download': 2}

    def test_unchanged_and_unknown_addition_do_not_mutate_approved_routes(self):
        self.assertEqual([], guard.evaluate(self.approved, [self.node, {'name': 'new-unapproved'}], self.usage, 100))

    def test_changed_credentials_are_withdrawn_without_being_installed(self):
        result = guard.evaluate(self.approved, [dict(self.node, password='rotated-test')], self.usage, 100)
        self.assertEqual('source_changed_requires_acceptance', result[0]['reason'])
        self.assertNotIn('password', str(result))

    def test_expiry_and_quota_fail_closed(self):
        for usage, expected in [(dict(self.usage, expire=399), 'expired_or_near_expiry'),
                                (dict(self.usage, download=999), 'quota_exhausted')]:
            self.assertEqual(expected, guard.evaluate(self.approved, [self.node], usage, 100)[0]['reason'])

    def test_missing_and_duplicate_name_never_silently_remap(self):
        for nodes in [[], [self.node, self.node]]:
            result = guard.evaluate(self.approved, nodes, self.usage, 100)
            self.assertEqual('missing_or_ambiguous_source', result[0]['reason'])
            self.assertEqual(359, result[0]['backend_id'])


class AllocationTest(unittest.TestCase):
    def test_live_contract_is_nested_and_separate_from_owned_nodes(self):
        import json
        data = json.loads((Path(__file__).resolve().parents[2] / '.docker/upstream/allocation.json').read_text())
        routes = data['routes']
        self.assertEqual([8, 16, 28, 41], [sum(r['tier'] <= tier for r in routes) for tier in range(1, 5)])
        self.assertEqual(82, len({r[k] for r in routes for k in ('backend_id', 'public_id')}))
        self.assertFalse(set(data['ordinary_owned_ids']) & {r['public_id'] for r in routes})
        self.assertEqual(4, sum(r['low_traffic'] for r in routes))
        self.assertEqual(8, sum(r['udp_limited'] for r in routes))
        self.assertEqual({1, 2, 5}, {r['rate'] for r in routes})


if __name__ == '__main__':
    unittest.main()

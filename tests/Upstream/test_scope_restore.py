import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ROOT = Path(__file__).resolve().parents[2] / '.docker/upstream'
scope = load('scope_restore', ROOT / 'scope_restore.py')
prepare = load('scope_prepare_test', ROOT / 'prepare.py')


class FakePrepare:
    validate_scope = staticmethod(prepare.validate_scope)

    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.calls = []
        self.before_return = None

    def snapshot_database(self, allocation, manifest):
        self.calls.append((copy.deepcopy(allocation), bytes(manifest)))
        if self.before_return:
            self.before_return()
        return copy.deepcopy(self.snapshot)


class ScopeRestoreTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.private = self.root / 'private'
        self.private.mkdir(mode=0o700)
        self.plans = self.root / 'plans'
        self.sibling = self.root / 'tools'
        self.sibling.mkdir(mode=0o700)
        self.allocation_bytes = (ROOT / 'allocation.json').read_bytes()
        (self.sibling / 'allocation.json').write_bytes(self.allocation_bytes)
        allocation = json.loads(self.allocation_bytes)
        self.approved, snapshots = [], []
        for route in allocation['routes']:
            key = route['key']
            self.approved.append({**{field: route[field] for field in ('key', 'backend_id', 'public_id')},
                                  'source_name': 'private-source-' + key, 'source_sha256': 'a' * 64})
            backend = {'id': route['backend_id'], 'machine_id': 21, 'tags': ['upstream-extension-backend'],
                       'enabled': True, 'custom_outbounds': 'private-password-and-sni', 'group_ids': '[1,6]'}
            public = {'id': route['public_id'], 'parent_id': route['backend_id'], 'tags': ['upstream-extension-public'], 'show': True}
            state = {'backend': copy.deepcopy(backend), 'public': copy.deepcopy(public)}
            snapshots.append({'key': key, 'backend': backend, 'public': public, 'state': state, 'state_sha256': scope.digest(state)})
        self.snapshot = {'machine_id': 21, 'routes': snapshots}
        self.fake = FakePrepare(self.snapshot)
        self.write_approved()
        for name, value in [('PRIVATE_ROOT', self.private), ('PLAN_ROOT', self.plans), ('SIBLING', self.sibling)]:
            patcher = patch.object(scope, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def write_approved(self):
        path = self.private / 'approved.private'
        path.write_bytes(scope.canonical(self.approved))
        path.chmod(0o600)

    def audit(self):
        return scope.audit(self.fake, now=1000)

    def restore(self, report, **kwargs):
        return scope.restore(report['plan_id'], report['plan_sha256'], self.fake, now=kwargs.get('now', 1001))

    def plan_path(self, report):
        return self.plans / report['plan_id'] / 'scope-audit.private.json'

    def test_audit_is_readonly_private_and_report_redacts_raw_source_and_snapshot(self):
        before = copy.deepcopy(self.snapshot)
        report = self.audit()
        self.assertFalse(os.path.lexists(self.private/'manifest.private'))
        self.assertEqual(before, self.snapshot)
        self.assertEqual(41, len(report['routes']))
        self.assertFalse(report['database_mutated'])
        self.assertFalse(report['public_key_baseline_mutated'])
        self.assertFalse(report['source_baseline_mutated'])
        self.assertEqual(scope.ALLOCATION_BYTES_SHA, report['allocation_file_sha256'])
        self.assertEqual(scope.bytes_sha((self.private/'approved.private').read_bytes()), report['approved_file_sha256'])
        path = self.plan_path(report)
        self.assertEqual(0o700, path.parent.stat().st_mode & 0o777)
        self.assertEqual(0o600, path.stat().st_mode & 0o777)
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), report['plan_sha256'])
        self.assertEqual({'machine_id', 'routes'}, set(json.loads(self.fake.calls[0][1])))
        self.assertTrue(all(set(row) == {'key', 'backend_id', 'public_id'} for row in json.loads(self.fake.calls[0][1])['routes']))
        raw = json.dumps(report)
        self.assertNotIn('private-source-', raw)
        self.assertNotIn('private-password-and-sni', raw)
        self.assertEqual(hashlib.sha256(b'private-source-U01').hexdigest(), report['routes'][0]['source_name_sha256'])

    def test_restore_creates_exact_original_scope_and_keeps_db_and_trust_unchanged(self):
        before = (copy.deepcopy(self.snapshot), (self.private/'approved.private').read_bytes())
        audit = self.audit()
        result = self.restore(audit)
        saved = self.private / 'manifest.private'
        plan = json.loads(self.plan_path(audit).read_bytes())
        self.assertEqual(scope.canonical(plan['manifest']), saved.read_bytes())
        self.assertEqual(0o600, saved.stat().st_mode & 0o777)
        self.assertEqual(before, (self.snapshot, (self.private/'approved.private').read_bytes()))
        self.assertEqual('scope_restored', result['status'])
        self.assertEqual(audit['manifest_file_sha256'], result['manifest_file_sha256'])
        directory = self.plan_path(audit).parent
        intent = json.loads((directory/'scope-restore.intent.private.json').read_bytes())
        receipt = json.loads((directory/'scope-restore.receipt.private.json').read_bytes())
        self.assertTrue(intent['missing_before'])
        self.assertEqual(result, receipt['result'])
        self.assertEqual([], list(self.private.glob('.scope-manifest-*')))

    def test_existing_file_directory_or_dangling_symlink_never_audits_or_overwrites(self):
        target = self.private/'manifest.private'
        for form in ('file', 'directory', 'dangling'):
            if form == 'file': target.write_text('do-not-overwrite')
            elif form == 'directory': target.mkdir()
            else: target.symlink_to(self.private/'missing')
            with self.assertRaisesRegex(scope.ScopeError, '^manifest_exists$'): self.audit()
            self.assertEqual([], self.fake.calls)
            if form == 'directory': target.rmdir()
            else: target.unlink()
        report = self.audit()
        target.write_text('concurrent-owner')
        with self.assertRaisesRegex(scope.ScopeError, '^manifest_exists$'): self.restore(report)
        self.assertEqual('concurrent-owner', target.read_text())

    def test_permission_error_is_not_missing(self):
        original = Path.lstat
        def guarded(path):
            if path == self.private/'manifest.private': raise PermissionError('private path')
            return original(path)
        with patch.object(Path, 'lstat', guarded):
            with self.assertRaises(PermissionError): self.audit()
        self.assertEqual([], self.fake.calls)

    def test_approved_symlink_public_permissions_and_duplicate_keys_reject(self):
        path = self.private/'approved.private'
        path.chmod(0o644)
        with self.assertRaisesRegex(scope.ScopeError, '^private_file_invalid$'): self.audit()
        path.chmod(0o600)
        path.rename(self.private/'original')
        path.symlink_to(self.private/'original')
        with self.assertRaises(OSError): self.audit()
        path.unlink()
        path.write_bytes(b'[{"key":"U01","key":"U02"}]');path.chmod(0o600)
        with self.assertRaisesRegex(scope.ScopeError, '^duplicate_json_key$'): self.audit()

    def test_fixed_allocation_and_all_41_approved_ids_and_source_fingerprints_required(self):
        (self.sibling/'allocation.json').write_bytes(self.allocation_bytes + b' ')
        with self.assertRaisesRegex(scope.ScopeError, '^allocation_hash_mismatch$'): self.audit()
        (self.sibling/'allocation.json').write_bytes(self.allocation_bytes)
        for mutation in (lambda rows: rows.pop(), lambda rows: rows[0].update(backend_id=148),
                         lambda rows: rows[0].update(source_name=''), lambda rows: rows[0].update(source_sha256='private-invalid'),
                         lambda rows: rows[0].update(key='U42')):
            original = copy.deepcopy(self.approved)
            mutation(self.approved);self.write_approved()
            with self.assertRaisesRegex(scope.ScopeError, '^scope_invalid$'): self.audit()
            self.approved = original;self.write_approved()
        self.assertEqual([], self.fake.calls)

    def test_snapshot_machine_parent_tags_missing_rows_or_false_state_hash_rejected(self):
        for mutation in (lambda s: s.update(machine_id=20), lambda s: s['routes'].pop(),
                         lambda s: s['routes'][0]['public'].update(parent_id=148),
                         lambda s: s['routes'][0]['backend'].update(tags=[]),
                         lambda s: s['routes'][0].update(state_sha256='f'*64)):
            original = copy.deepcopy(self.snapshot)
            mutation(self.snapshot)
            with self.assertRaisesRegex(scope.ScopeError, '^snapshot_invalid$'): self.audit()
            self.snapshot.clear();self.snapshot.update(original)

    def test_duplicate_approved_source_names_reject_before_database_read(self):
        self.approved[1]['source_name'] = self.approved[0]['source_name']
        self.write_approved()
        with self.assertRaisesRegex(scope.ScopeError, '^scope_invalid$'): self.audit()
        self.assertEqual([], self.fake.calls)

    def test_restore_exact_audit_bytes_and_hash_required(self):
        report = self.audit()
        with self.assertRaisesRegex(scope.ScopeError, '^audit_hash_mismatch$'):
            scope.restore(report['plan_id'], 'f'*64, self.fake, now=1001)
        path = self.plan_path(report)
        path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaisesRegex(scope.ScopeError, '^audit_hash_mismatch$'): self.restore(report)
        self.assertFalse(os.path.lexists(self.private/'manifest.private'))

    def test_restore_rejects_approved_file_drift_even_if_json_meaning_is_same(self):
        report = self.audit()
        path = self.private/'approved.private'
        path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaisesRegex(scope.ScopeError, '^approved_file_drift$'): self.restore(report)
        self.assertFalse(os.path.lexists(self.private/'manifest.private'))

    def test_restore_rejects_any_complete_state_drift(self):
        report = self.audit()
        first = self.snapshot['routes'][0]
        first['state']['backend']['group_ids'] = '[1,2,6]'
        first['state_sha256'] = scope.digest(first['state'])
        with self.assertRaisesRegex(scope.ScopeError, '^snapshot_drift$'): self.restore(report)
        self.assertFalse(os.path.lexists(self.private/'manifest.private'))

    def test_expired_and_future_audit_never_reaches_database(self):
        report = self.audit()
        calls = len(self.fake.calls)
        for now in (999, 8201):
            with self.assertRaisesRegex(scope.ScopeError, '^audit_expired$'): self.restore(report, now=now)
        self.assertEqual(calls, len(self.fake.calls))

    def test_global_scope_lock_excludes_parallel_audit_and_restore(self):
        report = self.audit()
        with scope.root_lock():
            with self.assertRaisesRegex(scope.ScopeError, '^scope_restore_busy$'): self.audit()
            with self.assertRaisesRegex(scope.ScopeError, '^scope_restore_busy$'): self.restore(report)

    def test_approved_drift_during_db_read_and_manifest_created_during_audit_fail(self):
        def drift():
            path = self.private/'approved.private';path.write_bytes(path.read_bytes()+b' ')
        self.fake.before_return = drift
        with self.assertRaisesRegex(scope.ScopeError, '^approved_file_drift$'): self.audit()
        self.write_approved()
        self.fake.before_return = lambda: (self.private/'manifest.private').write_text('concurrent')
        with self.assertRaisesRegex(scope.ScopeError, '^manifest_exists$'): self.audit()

    def test_atomic_publish_cannot_replace_manifest_created_after_missing_check(self):
        report = self.audit()
        real_link = os.link
        def raced(source, target, **kwargs):
            target.write_text('other-owner')
            return real_link(source, target, **kwargs)
        with patch.object(scope.os, 'link', side_effect=raced):
            with self.assertRaisesRegex(scope.ScopeError, '^manifest_exists$'): self.restore(report)
        self.assertEqual('other-owner', (self.private/'manifest.private').read_text())
        self.assertEqual([], list(self.private.glob('.scope-manifest-*')))

    def test_post_publish_receipt_failure_is_unknown_and_never_removes_manifest(self):
        report = self.audit()
        real_write = scope.private_write
        def fail_receipt(path, value):
            if path.name == 'scope-restore.receipt.private.json': raise OSError('private exception')
            return real_write(path, value)
        with patch.object(scope, 'private_write', side_effect=fail_receipt):
            with self.assertRaisesRegex(scope.ScopeError, '^restore_outcome_unknown$'): self.restore(report)
        self.assertTrue((self.private/'manifest.private').is_file())
        with self.assertRaisesRegex(scope.ScopeError, '^manifest_exists$'): self.restore(report)

    def test_post_publish_temporary_cleanup_failure_is_unknown_and_keeps_manifest(self):
        report = self.audit()
        real_unlink = Path.unlink
        def failed_cleanup(path, *args, **kwargs):
            if path.name.startswith('.scope-manifest-'): raise OSError('private cleanup failure')
            return real_unlink(path, *args, **kwargs)
        with patch.object(Path, 'unlink', failed_cleanup):
            with self.assertRaisesRegex(scope.ScopeError, '^restore_outcome_unknown$'): self.restore(report)
        self.assertTrue((self.private/'manifest.private').is_file())
        with self.assertRaisesRegex(scope.ScopeError, '^manifest_exists$'): self.restore(report)

    def test_all_uncaught_errors_and_invalid_arguments_are_redacted(self):
        with patch.object(scope, 'main', side_effect=RuntimeError('private-password-and-sni')):
            output = io.StringIO()
            with contextlib.redirect_stdout(output): self.assertEqual(1, scope.safe_main())
            self.assertNotIn('private-password', output.getvalue())
            self.assertEqual('scope_restore_failed', json.loads(output.getvalue())['reason'])
        output = io.StringIO()
        with contextlib.redirect_stdout(output): self.assertEqual(1, scope.safe_main(['private-password-and-sni']))
        self.assertNotIn('private-password', output.getvalue())
        self.assertEqual('invalid_arguments', json.loads(output.getvalue())['reason'])


if __name__ == '__main__':
    unittest.main()

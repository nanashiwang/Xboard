import base64
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2] / '.docker/upstream'
spec = importlib.util.spec_from_file_location('maintain', ROOT / 'maintain.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class FakeBackend:
    def __init__(self, states, manifest):
        self.states, self.mapping = copy.deepcopy(states), manifest
        self.events = []
        self.mutations = 0
        self.fail_after_mutation = False
        self.invalid_response = False
        self.readback_fails = False

    def manifest(self):
        self.events.append('manifest')
        return m.canonical(self.mapping)

    def snapshot(self, keys):
        self.events.append('snapshot')
        if self.readback_fails and self.mutations:
            raise RuntimeError('private-do-not-print')
        return [dict(key=key, backend_id=self.states[key]['backend']['id'], public_id=self.states[key]['public']['id'],
                     state=copy.deepcopy(self.states[key]), state_sha256=m.digest(self.states[key])) for key in keys]

    def mutate(self, request):
        self.events.append('mutate')
        self.mutations += 1
        answers = []
        for row in request['routes']:
            state = self.states[row['key']]
            if m.digest(state) != row['expected_sha256']:
                raise RuntimeError('hash-drift')
            action = request['action']
            if action in ('withdraw', 'rollback'):
                state['backend']['enabled'] = 0
                state['public']['show'] = 0
                if action == 'rollback':
                    state['backend']['custom_outbounds'] = row['original_state']['backend']['custom_outbounds']
            elif action == 'apply_hidden':
                entries = json.loads(row['original_state']['backend']['custom_outbounds'])
                settings = entries[0]['settings']
                settings['server'] = row['identity']['ip']
                if entries[0]['protocol'] != 'vless':
                    settings['tls']['certificate_public_key_sha256'] = [row['identity']['pin']]
                state['backend']['custom_outbounds'] = m.canonical(entries).decode()
                state['backend']['enabled'] = 1
                state['public']['show'] = 0
            elif action == 'publish':
                state['public']['show'] = row['original_state']['public']['show']
            answers.append(dict(key=row['key'], backend_id=row['backend_id'], public_id=row['public_id'], state_sha256=m.digest(state)))
        if self.fail_after_mutation:
            raise RuntimeError('secret-url-token-do-not-print')
        response = dict(schema=1, action=request['action'], plan_id=request['plan_id'], routes=answers)
        if self.invalid_response:
            response['private_password'] = 'do-not-print'
        return response


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.plans = self.root / 'plans'; self.plans.mkdir(mode=0o700)
        self.private = self.root / 'private'; self.private.mkdir(mode=0o700)
        self.plan_id = '1' * 32
        self.directory = self.plans / self.plan_id; self.directory.mkdir(mode=0o700)
        self.allocation = json.loads((ROOT / 'allocation.json').read_bytes())
        self.now = 1000
        self.source, self.approved, self.states, self.rows = [], [], {}, []
        self.pin = base64.b64encode(b'a' * 32).decode()
        self.new_pin = base64.b64encode(b'b' * 32).decode()
        for scope in self.allocation['routes']:
            key, protocol = scope['key'], scope['upstream_type']
            source = dict(name='source-' + key, type=protocol, password='test-only-password', server='provider.test.invalid', port=443, sni='sni.test.invalid')
            approved = dict(key=key, backend_id=scope['backend_id'], public_id=scope['public_id'], source_name=source['name'], source_sha256=m.digest(source))
            tls = dict(enabled=True, insecure=False, server_name='sni.test.invalid')
            if protocol != 'vless': tls['certificate_public_key_sha256'] = [self.pin]
            settings = dict(server='8.8.4.4', server_port=443, password='test-only-password', tls=tls)
            state = dict(backend=dict(id=scope['backend_id'], machine_id=21, enabled=1, show=0, type='vless', tags='["upstream-extension-backend"]', group_ids='[1,6]', rate='1.0', protocol_settings='{"unchanged":true}', custom_outbounds=m.canonical([dict(protocol=protocol, settings=settings)]).decode()), public=dict(id=scope['public_id'], parent_id=scope['backend_id'], enabled=1, show=1, type='vless', tags='["upstream-extension-public"]'))
            identity = dict(key=key, ip='8.8.8.8', port=443, sni='sni.test.invalid', pin=self.new_pin)
            candidate = dict(identity=identity, candidate_digest=m.digest(identity), old_pin_matches=False, source_dns_endpoint=True, current_endpoint=False, certificate_time_valid=True, not_before=900, not_after=2000)
            self.source.append(source); self.approved.append(approved); self.states[key] = state
            self.rows.append(dict(key=key, approved=approved, source=source, observed_source_sha=m.digest(source), snapshot=dict(state=state, state_sha256=m.digest(state)), candidates=[candidate]))
        self.manifest = dict(machine_id=21, routes=[{k:r[k] for k in ('key','backend_id','public_id')} for r in self.approved])
        self.backend = FakeBackend(self.states, self.manifest)
        self.approved_bytes = m.canonical(self.approved)
        m.private_write(self.private / 'approved.private', self.approved_bytes)
        m.private_write(self.private / 'pinned.private', b'[{"test":"old-map"}]')
        self.plan = dict(schema=1, plan_id=self.plan_id, prepared_at=1000, allocation_sha256=m.digest(self.allocation), approved_file_sha256=m.bytes_sha(self.approved_bytes), manifest_file_sha256=m.bytes_sha(m.canonical(self.manifest)), routes=self.rows)
        self.write_plan()
        self.selection = {'U01':self.rows[0]['candidates'][0]['candidate_digest']}
        self.usage = dict(expire=100000,total=10000,upload=1,download=2)
        self.driver = m.Driver(self.backend, plan_root=self.plans, private_root=self.private, sibling=ROOT,
                               fetch=lambda:(copy.deepcopy(self.source),self.usage), backup=self.backup, clock=lambda:self.now)

    def tearDown(self): self.temp.cleanup()

    def write_plan(self):
        path = self.directory / 'plan.private.json'
        path.unlink(missing_ok=True)
        body = m.canonical(self.plan); m.private_write(path,body); self.plan_sha = m.bytes_sha(body)

    def backup(self, directory):
        self.backend.events.append('backup')
        m.private_write(directory/'database.sqlite',b'fake-test-backup')
        return dict(database_file='database.sqlite',database_sha256=hashlib.sha256(b'fake-test-backup').hexdigest())

    def run_action(self, action, selection=None):
        return self.driver.run(self.plan_id,self.plan_sha,self.selection if selection is None else selection,action)

    def rejects(self, reason, call):
        with self.assertRaises(m.MaintenanceError) as caught:call()
        self.assertEqual(reason,str(caught.exception))

    def test_happy_stages_backup_first_scope_and_private_modes(self):
        untouched=copy.deepcopy(self.backend.states['U02'])
        for action in m.ACTIONS:self.assertEqual('applied',self.run_action(action)['status'])
        self.assertLess(self.backend.events.index('backup'),self.backend.events.index('mutate'))
        self.assertEqual(1,self.backend.events.count('backup'))
        self.assertEqual(untouched,self.backend.states['U02'])
        self.assertFalse(self.backend.states['U01']['backend']['enabled']);self.assertFalse(self.backend.states['U01']['public']['show'])
        for path in self.directory.rglob('*'):
            self.assertEqual(0,path.stat().st_mode & 0o077)
        output=m.canonical(self.run_action('rollback')).decode()
        for secret in ('test-only-password','sni.test.invalid','provider.test.invalid',self.new_pin):self.assertNotIn(secret,output)

    def test_same_action_retry_is_idempotent_without_replay(self):
        first=self.run_action('withdraw');again=self.run_action('withdraw')
        self.assertEqual('already_applied',again['status']);self.assertEqual(first['routes'],again['routes']);self.assertEqual(1,self.backend.mutations)

    def test_ambiguous_commit_blocks_retry_and_rollback(self):
        self.backend.fail_after_mutation=True
        self.rejects('action_outcome_unknown',lambda:self.run_action('withdraw'))
        self.rejects('previous_outcome_unknown',lambda:self.run_action('withdraw'))
        self.rejects('previous_outcome_unknown',lambda:self.run_action('rollback'))
        self.assertEqual(1,self.backend.mutations)

    def test_post_write_readback_failure_is_ambiguous(self):
        self.backend.readback_fails=True
        self.rejects('action_outcome_unknown',lambda:self.run_action('withdraw'))
        self.assertEqual(1,self.backend.mutations)

    def test_plan_bytes_and_approved_file_tamper_rejected(self):
        self.rejects('plan_bytes_mismatch',lambda:self.driver.run(self.plan_id,'0'*64,self.selection,'withdraw'))
        (self.private/'approved.private').write_bytes(self.approved_bytes+b' ')
        self.rejects('approved_file_drift',lambda:self.run_action('withdraw'));self.assertEqual(0,self.backend.mutations)

    def test_selection_has_no_free_ip_pin_input_or_unknown_candidate(self):
        self.rejects('selection_invalid',lambda:self.run_action('withdraw',{'U01':{'ip':'8.8.8.8','pin':self.new_pin}}))
        self.rejects('candidate_not_unique',lambda:self.run_action('withdraw',{'U01':'0'*64}))
        self.rejects('selection_invalid',lambda:self.run_action('withdraw',{'U42':'0'*64}))
        self.assertEqual(0,self.backend.mutations)

    def test_new_pin_requires_current_source_dns_and_time_valid(self):
        self.rows[0]['candidates'][0]['source_dns_endpoint']=False;self.write_plan()
        self.rejects('new_pin_requires_source_endpoint',lambda:self.run_action('withdraw'))
        self.rows[0]['candidates'][0]['source_dns_endpoint']=True;self.rows[0]['candidates'][0]['not_after']=999;self.write_plan()
        self.rejects('candidate_certificate_expired',lambda:self.run_action('withdraw'))

    def test_tls_contract_is_rejected_before_withdraw_if_insecure_field_missing(self):
        state=self.rows[0]['snapshot']['state'];entries=json.loads(state['backend']['custom_outbounds'])
        del entries[0]['settings']['tls']['insecure']
        state['backend']['custom_outbounds']=m.canonical(entries).decode()
        self.rows[0]['snapshot']['state_sha256']=m.digest(state);self.write_plan()
        self.rejects('candidate_contract_invalid',lambda:self.run_action('withdraw'))
        self.assertEqual(0,self.backend.mutations)

    def test_plan_expiry_does_not_prevent_known_state_rollback(self):
        self.run_action('withdraw');self.run_action('apply_hidden');self.now=10000
        self.rejects('plan_expired',lambda:self.run_action('publish'))
        self.driver.fetch=lambda:(_ for _ in ()).throw(RuntimeError('secret-token'))
        self.assertEqual('applied',self.run_action('rollback')['status'])

    def test_source_drift_quota_and_secret_exception_no_mutation(self):
        self.source[0]['password']='new-secret'
        self.rejects('source_fingerprint_changed',lambda:self.run_action('withdraw'))
        self.driver.fetch=lambda:(_ for _ in ()).throw(RuntimeError('secret-token-url'))
        self.rejects('source_fetch_failed',lambda:self.run_action('withdraw'))
        self.driver.fetch=lambda:(self.source,dict(self.usage,total=1))
        self.rejects('source_quota_or_expiry',lambda:self.run_action('withdraw'))
        self.assertEqual(0,self.backend.mutations)

    def test_current_or_previous_receipt_hash_drift_not_overwritten(self):
        self.backend.states['U01']['backend']['group_ids']='[5]'
        self.rejects('current_state_drift',lambda:self.run_action('withdraw'))
        self.backend.states['U01']['backend']['group_ids']='[1,6]';self.run_action('withdraw')
        self.backend.states['U01']['backend']['protocol_settings']='{"concurrent":true}'
        self.rejects('current_state_drift',lambda:self.run_action('apply_hidden'));self.assertEqual(1,self.backend.mutations)

    def test_phase_and_scope_drift_rejected(self):
        self.rejects('withdraw_required',lambda:self.run_action('publish'))
        self.run_action('withdraw');self.rejects('operation_phase_invalid',lambda:self.run_action('publish'))
        self.backend.mapping['routes'][0]['backend_id']=148
        self.rejects('manifest_file_drift',lambda:self.run_action('rollback'))

    def test_backup_failure_happens_before_any_mutation(self):
        self.driver.backup=lambda _:(_ for _ in ()).throw(RuntimeError('secret-failure'))
        self.rejects('backup_failed',lambda:self.run_action('withdraw'));self.assertEqual(0,self.backend.mutations)

    def test_null_selection_only_withdraw_or_rollback(self):
        selection={'U01':None};self.run_action('withdraw',selection)
        self.rejects('no_approved_candidate',lambda:self.run_action('apply_hidden',selection))
        self.run_action('rollback',selection);self.assertFalse(self.backend.states['U01']['backend']['enabled'])

    def test_ca_identity_pin_normalized_without_changing_ca(self):
        selection={'U06':self.rows[5]['candidates'][0]['candidate_digest']}
        self.run_action('withdraw',selection);self.run_action('apply_hidden',selection)
        tls=json.loads(self.backend.states['U06']['backend']['custom_outbounds'])[0]['settings']['tls']
        self.assertNotIn('certificate_public_key_sha256',tls);self.assertFalse(tls['insecure'])

    def test_selection_subset_is_bound_between_stages(self):
        self.run_action('withdraw')
        other={'U02':self.rows[1]['candidates'][0]['candidate_digest']}
        self.rejects('withdraw_required',lambda:self.run_action('apply_hidden',other));self.assertEqual(1,self.backend.mutations)

    def test_private_symlink_or_readable_file_rejected(self):
        path=self.directory/'plan.private.json';path.chmod(0o644)
        self.rejects('private_file_invalid',lambda:self.run_action('withdraw'))
        path.chmod(0o600);other=self.directory/'actual.private';path.rename(other);path.symlink_to(other)
        with self.assertRaises(OSError):self.run_action('withdraw')
        self.assertEqual(0,self.backend.mutations)

    def test_exclusive_lock_rejects_parallel_operation(self):
        with m.exclusive_plan(self.directory):self.rejects('maintenance_busy',lambda:self.run_action('withdraw'))

    def test_unexpected_private_backend_response_never_emitted(self):
        self.backend.invalid_response=True
        self.rejects('action_outcome_unknown',lambda:self.run_action('withdraw'))
        self.assertEqual(1,self.backend.mutations)

    def test_duplicate_selection_keys_and_nonfinite_json_are_rejected(self):
        self.rejects('duplicate_json_key',lambda:m.parse_json('{"U01":null,"U01":"'+'a'*64+'"}'))
        self.rejects('invalid_number',lambda:m.parse_json('{"test":NaN}'))

    def docker_backend(self, fail_copy=False, fail_cleanup=False, temp_path=None):
        backend = m.DockerBackend(sibling=ROOT, private_root=self.private)
        calls = []
        def run(command, body=None, timeout=60):
            calls.append((command, body))
            if command[1:4] == ['compose', 'ps', '-q']:
                return b'a' * 64
            if 'mktemp' in command:
                return (temp_path or '/tmp/xboard-upstream-maintain.TEST1234').encode()
            if fail_copy and command[1] == 'cp':
                raise m.MaintenanceError('container_execution_failed')
            if fail_cleanup and 'rm' in command:
                raise m.MaintenanceError('container_execution_failed')
            return b''
        backend.run = run
        return backend, calls

    def test_host_manifest_required_private_and_scope_checked_before_container(self):
        backend, calls = self.docker_backend()
        self.rejects('host_manifest_missing',backend.__enter__)
        self.assertEqual([],calls)
        path=self.private/'manifest.private';m.private_write(path,m.canonical(self.manifest));path.chmod(0o644)
        self.rejects('private_file_invalid',backend.__enter__);self.assertEqual([],calls)
        path.chmod(0o600);bad=copy.deepcopy(self.manifest);bad['routes'][0]['backend_id']=148;path.write_bytes(m.canonical(bad))
        self.rejects('scope_invalid',backend.__enter__);self.assertEqual([],calls)

    def test_host_manifest_private_stdin_and_scoped_cleanup(self):
        body=m.canonical(self.manifest);m.private_write(self.private/'manifest.private',body)
        backend,calls=self.docker_backend()
        with backend:
            self.assertEqual(body,backend.manifest())
            self.assertTrue(any('chmod' in argv and '700' in argv for argv,_ in calls))
            private_calls=[(argv,payload) for argv,payload in calls if payload is not None]
            self.assertEqual(1,len(private_calls));self.assertEqual(body,private_calls[0][1])
            self.assertNotIn(body.decode(),' '.join(private_calls[0][0]))
            self.assertIn('0600',private_calls[0][0][-2])
        removed=[argv for argv,_ in calls if 'rm' in argv]
        self.assertEqual(1,len(removed));self.assertEqual(3,len([arg for arg in removed[0] if arg.startswith('/tmp/')]))
        self.assertTrue(all(arg.startswith('/tmp/xboard-upstream-maintain.TEST1234/') for arg in removed[0] if arg.startswith('/tmp/')))
        self.assertTrue(any('rmdir' in argv for argv,_ in calls));self.assertIsNone(backend.manifest_bytes)

    def test_setup_failure_cleans_only_validated_directory(self):
        m.private_write(self.private/'manifest.private',m.canonical(self.manifest))
        backend,calls=self.docker_backend(fail_copy=True)
        self.rejects('container_execution_failed',backend.__enter__)
        self.assertTrue(any('rm' in argv for argv,_ in calls))
        backend,calls=self.docker_backend(temp_path='/root/not-allowed')
        self.rejects('container_directory_invalid',backend.__enter__)
        self.assertFalse(any('rm' in argv or 'rmdir' in argv for argv,_ in calls))

    def test_cleanup_failure_is_visible_without_masking_prior_failure(self):
        m.private_write(self.private/'manifest.private',m.canonical(self.manifest))
        backend,_=self.docker_backend(fail_cleanup=True);backend.__enter__()
        self.rejects('private_temp_cleanup_failed',lambda:backend.__exit__(None,None,None))
        backend,_=self.docker_backend(fail_copy=True,fail_cleanup=True)
        self.rejects('container_execution_failed',backend.__enter__)

    def test_real_online_sqlite_backup_is_verified_before_mutation(self):
        database=self.root/'live.sqlite'
        with sqlite3.connect(database) as db:
            db.execute('PRAGMA journal_mode=WAL');db.execute('CREATE TABLE evidence(value)');db.execute('INSERT INTO evidence VALUES(7)')
        self.driver.database=database;self.driver.backup=self.driver.backup_live
        self.run_action('withdraw')
        backups=list(self.directory.glob('maintenance-*/backup/before-deploy-*.sqlite'));self.assertEqual(1,len(backups))
        with sqlite3.connect(backups[0]) as db:
            self.assertEqual([('ok',)],db.execute('PRAGMA integrity_check').fetchall());self.assertEqual([(7,)],db.execute('SELECT value FROM evidence').fetchall())


if __name__=='__main__':unittest.main()

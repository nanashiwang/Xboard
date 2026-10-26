import base64
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

SIBLING = Path(__file__).resolve().parents[2] / '.docker/upstream'
sys.path.insert(0, str(SIBLING))
import entry_identity as entry
import guard


class EntryIdentityTest(unittest.TestCase):
    def setUp(self):
        self.allocation = json.loads((SIBLING/'allocation.json').read_text())
        self.approved = [guard.route_result(r) for r in self.allocation['routes']]
        self.maps = [dict(key=r['key'], ip='2606:4700:4700::1111', port=443, sni='fixture.invalid',
                          pin=base64.b64encode(b'a'*32).decode())
                     for r in self.allocation['routes'] if r['upstream_type']=='anytls']
        self.request = {'schema':1, 'nonce':'a'*64, 'mappings':self.maps}

    def response(self, request, failed=None):
        return entry.serve(request, self.allocation,
                           lambda m:'runtime_public_key_mismatch' if m['key'] in (failed or []) else None)

    def run_check(self, exchange=None, **kwargs):
        return entry.evaluate_identity(self.approved, self.allocation, kwargs.get('mappings', self.maps),
                                       exchange=exchange or self.response)

    def test_all_28_only_certificate_checks_and_exact_singapore_rejection(self):
        result=self.run_check(lambda request:self.response(request, {'U04','U05'}))
        self.assertEqual(28,len(result))
        self.assertEqual(['U04','U05'],[r['key'] for r in result if 'reason' in r])
        self.assertEqual([365,367],[r['backend_id'] for r in result if 'reason' in r])
        self.assertNotIn('fixture.invalid',json.dumps(result))
        self.assertNotIn(self.maps[0]['pin'],json.dumps(result))

    def test_transport_timeout_or_host_verification_error_fails_all_without_local_fallback(self):
        for error in (subprocess.TimeoutExpired('ssh',40), OSError('private endpoint'), ValueError('bad host')):
            with self.subTest(error=type(error).__name__), patch.object(guard,'probe_identity') as local:
                def fail(_):raise error
                result=self.run_check(fail)
                self.assertEqual(28,len(result))
                self.assertTrue(all(r.get('reason')=='runtime_identity_check_failed' for r in result))
                local.assert_not_called()

    def test_mismatched_nonce_hash_scope_counts_and_unknown_fields_fail_closed(self):
        mutations=[lambda r:r.update(nonce='b'*64),lambda r:r.update(request_sha256='0'*64),
                   lambda r:r.update(checked_at=int(time.time())-300),lambda r:r.update(checked_at=True),
                   lambda r:r.update(schema=True),lambda r:r.update(extra=True),
                   lambda r:r['identity_checks'].pop(),lambda r:r['identity_checks'].append(r['identity_checks'][0]),
                   lambda r:r['identity_checks'][0].update(backend_id=1),
                   lambda r:r['identity_checks'][0].update(reason='unknown'),
                   lambda r:r['identity_checks'][0].update(reason=None),
                   lambda r:r['identity_checks'][0].update(secret='forbidden'),
                   lambda r:r['identity_checks'].__setitem__(1,r['identity_checks'][0])]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                def exchange(request):
                    response=self.response(request);mutate(response);return response
                self.assertTrue(all('reason' in r for r in self.run_check(exchange)))

    def test_invalid_mapping_never_sent_and_cannot_be_overridden_by_worker(self):
        seen=[];maps=copy.deepcopy(self.maps);maps[0]['pin']='bad'
        def exchange(request):seen.extend(r['key'] for r in request['mappings']);return self.response(request)
        result=self.run_check(exchange,mappings=maps)
        self.assertNotIn('U01',seen)
        self.assertEqual('runtime_identity_mapping_invalid',result[0]['reason'])
        self.assertEqual(27,len(seen))

    def test_worker_rejects_private_local_non_anytls_and_extra_credentials(self):
        for mutate in (lambda r:r['mappings'][0].update(ip='127.0.0.1'),
                       lambda r:r['mappings'][0].update(ip='10.1.1.1'),
                       lambda r:r['mappings'][0].update(ip='::1'),
                       lambda r:r['mappings'][0].update(ip='::ffff:127.0.0.1'),
                       lambda r:r['mappings'][0].update(key='U18'),
                       lambda r:r['mappings'][0].update(password='must-not-cross'),
                       lambda r:r['mappings'].append(r['mappings'][0]),
                       lambda r:r.update(nonce='bad')):
            req=copy.deepcopy(self.request);mutate(req)
            with self.assertRaises(ValueError),patch.object(guard,'probe_identity') as probe:
                entry.serve(req,self.allocation)
            probe.assert_not_called()

    def test_duplicate_and_oversized_json_rejected(self):
        for raw in (b'{"schema":1,"schema":1}',b' '*65537,b'{"x":NaN}'):
            with self.assertRaises(ValueError):entry.decode(raw)

    def test_ssh_uses_pinned_host_and_dedicated_key_no_destinations_in_argv(self):
        answer=self.response(self.request)
        with patch.object(subprocess,'run',return_value=subprocess.CompletedProcess([],0,entry.encode(answer),b'')) as run:
            self.assertEqual(answer,entry.ssh_exchange(self.request))
        args=run.call_args.args[0]
        self.assertIn('StrictHostKeyChecking=yes',args)
        self.assertIn('IdentitiesOnly=yes',args)
        self.assertIn('GlobalKnownHostsFile=/dev/null',args)
        self.assertEqual(40,run.call_args.kwargs['timeout'])
        self.assertEqual(self.request,entry.decode(run.call_args.kwargs['input']))
        self.assertNotIn(self.maps[0]['ip'],' '.join(args))
        self.assertNotIn(self.maps[0]['pin'],' '.join(args))

    def test_bad_ssh_exit_stderr_and_oversized_stdout_rejected(self):
        for result in (subprocess.CompletedProcess([],255,b'{}',b''),
                       subprocess.CompletedProcess([],0,b'{}',b'warning'),
                       subprocess.CompletedProcess([],0,b' '*65537,b'')):
            with patch.object(subprocess,'run',return_value=result), self.assertRaises(ValueError):
                entry.ssh_exchange(self.request)

    def test_metadata_grace_does_not_hide_remote_mismatch(self):
        approved=[dict(r,source_name=r['key'],source_sha256='0'*64) for r in self.approved]
        def fail():raise OSError()
        state=guard.check(approved,{'last_success_at':100,'usage':{'expire':10000}},self.allocation,self.maps,
                          200,fail,identity_evaluator=lambda *a:entry.evaluate_identity(*a,exchange=lambda req:self.response(req,{'U04'})))
        self.assertFalse(state['fetch_ok'])
        self.assertEqual(['U04'],[r['key'] for r in state['withdraw']])

    def test_readonly_subset_and_success_never_mutate_inputs(self):
        before=copy.deepcopy((self.approved,self.maps))
        result=entry.evaluate_identity([r for r in self.approved if r['key']=='U04'],self.allocation,self.maps,
                                       exchange=self.response)
        self.assertEqual([{'key':'U04','backend_id':365,'public_id':366}],result)
        self.assertEqual(before,(self.approved,self.maps))


if __name__=='__main__':unittest.main()

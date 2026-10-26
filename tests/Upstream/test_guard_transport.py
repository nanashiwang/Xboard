import base64
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2] / '.docker/upstream'
spec=importlib.util.spec_from_file_location('guard_transport',ROOT/'guard.py')
g=importlib.util.module_from_spec(spec);spec.loader.exec_module(g)

class TransportTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.manifest={'machine_id':21,'private_password':'never-send-this', 'routes':[dict(key='U%02d'%n,backend_id=357+2*n,public_id=358+2*n,private_endpoint='never-send-endpoint') for n in range(1,42)]}
        self.write_manifest();shutil.copy(ROOT/'guard-apply.php',self.root/'guard-apply.php')
        self.request=[dict(key='U04',backend_id=365,public_id=366,reason='runtime_public_key_mismatch')]

    def tearDown(self):self.temp.cleanup()

    def write_manifest(self):
        self.path=self.root/'manifest.private';self.path.write_text(json.dumps(self.manifest));self.path.chmod(0o600)

    def rejected_without_process(self,callback):
        with patch.object(g.subprocess,'run') as run:
            with self.assertRaises((ValueError,OSError)):callback()
            run.assert_not_called()

    def test_only_stdin_transports_minimal_manifest_and_request_no_private_files(self):
        before={p.name:p.read_bytes() for p in self.root.iterdir()}
        with patch.object(g.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'{"withdrawn":["U04"]}','')) as run:
            self.assertEqual({'withdrawn':['U04']},g.apply(self.request,self.root))
        run.assert_called_once();args,kwargs=run.call_args
        self.assertEqual(['docker','compose','exec','-T','xboard','php'],args[0])
        self.assertEqual('/root/Xboard',kwargs['cwd']);self.assertTrue(kwargs['capture_output'])
        script=kwargs['input'];self.assertNotIn('__XBOARD_GUARD_',script)
        normalized=g.private_manifest(self.root);request=g.withdrawal_request(self.request,normalized)
        for value in (normalized,request):
            token=base64.b64encode(json.dumps(value,separators=(',',':')).encode()).decode()
            self.assertIn(token,script);self.assertNotIn(token,' '.join(args[0]))
        for secret in ('never-send-this','never-send-endpoint'):
            self.assertNotIn(secret,script);self.assertNotIn(base64.b64encode(secret.encode()).decode(),script)
        self.assertEqual(before,{p.name:p.read_bytes() for p in self.root.iterdir()})

    def test_host_missing_readable_symlink_or_nonregular_manifest_rejected(self):
        self.path.unlink();self.rejected_without_process(lambda:g.apply(self.request,self.root))
        self.write_manifest();self.path.chmod(0o644);self.rejected_without_process(lambda:g.apply(self.request,self.root))
        self.path.chmod(0o600);real=self.root/'actual.private';self.path.rename(real);self.path.symlink_to(real)
        self.rejected_without_process(lambda:g.apply(self.request,self.root))
        self.path.unlink();self.path.mkdir();self.rejected_without_process(lambda:g.apply(self.request,self.root))

    def test_duplicate_manifest_json_keys_are_not_silently_accepted(self):
        self.path.write_text('{"machine_id":22,"machine_id":21,"routes":[]}')
        self.rejected_without_process(lambda:g.apply(self.request,self.root))

    def test_manifest_machine_scope_duplicate_missing_or_id_drift_rejected(self):
        original=copy.deepcopy(self.manifest)
        for mutate in (lambda m:m.update(machine_id=22),lambda m:m['routes'].pop(),lambda m:m['routes'].__setitem__(40,m['routes'][0]),lambda m:m['routes'][0].update(backend_id=148),lambda m:m['routes'][0].update(key='U42')):
            self.manifest=copy.deepcopy(original);mutate(self.manifest);self.write_manifest()
            self.rejected_without_process(lambda:g.apply(self.request,self.root))

    def test_request_strict_fields_scope_reason_ids_and_duplicates(self):
        invalid=[[],self.request*2,[dict(self.request[0],password='injected')],[dict(self.request[0],key='U42')],[dict(self.request[0],backend_id=148)],[dict(self.request[0],reason='allow')]]
        for request in invalid:self.rejected_without_process(lambda:g.apply(request,self.root))

    def test_template_requires_exactly_one_of_each_marker(self):
        path=self.root/'guard-apply.php';original=path.read_text()
        for value in (original.replace('__XBOARD_GUARD_MANIFEST_BASE64__',''),original+'\n__XBOARD_GUARD_REQUEST_BASE64__'):
            path.write_text(value);self.rejected_without_process(lambda:g.apply(self.request,self.root))

    def test_response_redacts_errors_and_rejects_unrequested_or_private_fields(self):
        for response,code in [('{"error":"secret-do-not-print"}',1),('{"withdrawn":["U05"]}',0),('{"withdrawn":["U04","U04"]}',0),('{"withdrawn":[],"password":"secret"}',0),('bad-private-output',0),('[]',0)]:
            with patch.object(g.subprocess,'run',return_value=subprocess.CompletedProcess([],code,response,'private-stderr')):
                with self.assertRaisesRegex(RuntimeError,'^withdrawal_failed$'):g.apply(self.request,self.root)

    def test_php_template_has_no_container_private_file_or_write_dependency(self):
        source=(ROOT/'guard-apply.php').read_text()
        for value in ('/storage/app/backups/','guard.request.json','file_get_contents','file_put_contents'):
            self.assertNotIn(value,source)
        self.assertIn('DB::transaction',source);self.assertIn("['show'=>false]",source);self.assertIn("['enabled'=>false]",source)

if __name__=='__main__':unittest.main()

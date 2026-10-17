import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch, MagicMock

spec = importlib.util.spec_from_file_location('probe', Path(__file__).resolve().parents[2] / 'tools/node-probe/probe.py')
p = importlib.util.module_from_spec(spec); spec.loader.exec_module(p)

class AgentTest(unittest.TestCase):
    def test_transient_report_retry_keeps_identity_and_never_retries_auth_rejection(self):
        with tempfile.TemporaryDirectory() as folder:
            a=p.Agent({'panel_url':'https://panel.test','token':'a'*64},folder)
            response=MagicMock();response.__enter__.return_value.read.return_value=b'{"data":{"accepted":false}}'
            sample={'sample_id':'00000000-0000-4000-8000-000000000001'}
            with patch.object(a.http,'open',side_effect=[TimeoutError(),response]) as send,patch.object(p.STOP,'wait',return_value=False):
                self.assertEqual(a.post('report',sample),{'accepted':False})
                self.assertEqual(send.call_count,2)
                self.assertEqual(send.call_args_list[0].args[0].data,send.call_args_list[1].args[0].data)
            denied=p.urllib.error.HTTPError('https://panel.test',403,'denied',{},None)
            with patch.object(a.http,'open',side_effect=denied) as send:
                with self.assertRaises(p.urllib.error.HTTPError): a.post('report',sample)
                self.assertEqual(send.call_count,1)

    def test_panel_request_identifies_probe_without_browser_impersonation(self):
        with tempfile.TemporaryDirectory() as folder:
            a=p.Agent({'panel_url':'https://panel.test','token':'a'*64},folder)
            with patch.object(a.http,'open') as send:
                send.return_value.__enter__.return_value.read.return_value=b'{"data":{}}'
                self.assertEqual(a.post('config',{'agent_version':p.VERSION}),{})
                request=send.call_args.args[0]
                self.assertEqual(request.get_header('User-agent'),'Xboard-Node-Probe/'+p.VERSION)
                self.assertEqual(request.get_header('Authorization'),'Bearer '+'a'*64)
                self.assertEqual(request.full_url,'https://panel.test/api/v2/probe/config')

    def test_only_selected_outbound_and_no_direct_fallback(self):
        c=p.runtime_config({'type':'vless','server':'node.test','server_port':443,'uuid':'test'},1080)
        self.assertEqual(len(c['outbounds']),1); self.assertEqual(c['route']['final'],'node')
        self.assertEqual(c['inbounds'][0]['listen'],'127.0.0.1')
        for outbound in ({'type':'direct'},{'type':'vless','detour':'other'},{'type':'vless','tls':{'insecure':True}}):
            with self.assertRaises(ValueError): p.runtime_config(outbound,1080)

    def test_upload_requires_ack_and_bytes_and_ignores_proxy_environment(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'HTTPS_PROXY':'http://bad','NO_PROXY':'*'}):
            metrics={'http_code':200,'size_upload':262144,'time_total':1.5}
            with patch.object(p.subprocess,'run',return_value=subprocess.CompletedProcess([],0,json.dumps(metrics).encode(),b'')) as run:
                check,_=p.curl_check(1234,{'id':'upload','url':'https://target.test/up'},folder,262144)
                self.assertIsNone(check['error']); self.assertEqual(check['ms'],1500)
                args=run.call_args.args[0]; self.assertIn('socks5h://127.0.0.1:1234',args)
                self.assertNotIn('HTTPS_PROXY',run.call_args.kwargs['env']); self.assertNotIn('--insecure',args)
            for status, count, rc, expected in [(0,262144,28,'timeout'),(200,100,0,'incomplete'),(500,262144,0,'http')]:
                metrics.update(http_code=status,size_upload=count)
                with patch.object(p.subprocess,'run',return_value=subprocess.CompletedProcess([],rc,json.dumps(metrics).encode(),b'')):
                    check,_=p.curl_check(1234,{'id':'upload','url':'https://target.test/up'},folder,262144)
                    self.assertEqual(check['error'],expected)

    def test_download_checks_actual_body_size(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder,'download.body').write_bytes(b'short')
            with patch.object(p.subprocess,'run',return_value=subprocess.CompletedProcess([],0,b'{"http_code":200,"size_download":65536,"time_total":1}',b'')):
                c,_=p.curl_check(1234,{'id':'download','url':'https://target.test/down'},folder,65536)
                self.assertEqual(c['error'],'incomplete')

    def test_pinned_core_checks_vless_and_failed_proxy_never_succeeds_directly(self):
        # Executes real sing-box and curl when available (CI Docker image).
        if not __import__('shutil').which('sing-box'): self.skipTest('sing-box requires probe image')
        config={'targets':[{'id':'cloudflare','url':'https://example.com','status':200},{'id':'google','url':'https://example.com','status':204}]}
        node={'id':1,'outbound':{'type':'vless','server':'127.0.0.1','server_port':1,'uuid':'00000000-0000-4000-8000-000000000001'}}
        result=p.measure(node,config,False)
        self.assertNotIn('error',result); self.assertEqual(len(result['checks']),2)
        self.assertTrue(all(c['error'] and c['status']==0 for c in result['checks']))

    def test_config_errors_do_not_make_network_requests(self):
        with patch.object(p,'curl_check') as call:
            r=p.measure({'id':7,'error':'account_unavailable'},{},True)
            self.assertEqual(r['checks'],[]); self.assertEqual(r['error'],'account_unavailable'); call.assert_not_called()

    def test_transfer_budget_persists_and_no_redirect_or_http_panel(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError): p.Agent({'panel_url':'http://panel.test','token':'a'*64},folder)
            a=p.Agent({'panel_url':'https://panel.test','token':'a'*64},folder)
            cfg={'version':1,'nodes':[{'id':1}],'interval_seconds':60,'transfer_interval_seconds':1800,'transfer_bytes':262144}
            with patch.object(a,'post',side_effect=lambda path,data:cfg if path=='config' else {}),patch.object(p,'measure',return_value={'server_id':1,'checked_at':1,'checks':[]}) as measure:
                a.cycle(); self.assertTrue(measure.call_args.args[2]); a.cycle(); self.assertFalse(measure.call_args.args[2])
            b=p.Agent({'panel_url':'https://panel.test','token':'a'*64},folder); self.assertIn('1',b.transfers)
            self.assertIsNone(p.NoRedirect().redirect_request(None,None,None,None,None,None))

if __name__=='__main__': unittest.main()

import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

root=Path(__file__).resolve().parents[2]
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,root/path)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
p=module('probe','tools/node-probe/probe.py')
m=module('monitor','tools/ingress-monitor/monitor.py')

class IngressTest(unittest.TestCase):
    def test_direct_health_requires_body_tls_no_proxy_and_no_redirect(self):
        def run(args,**kwargs):
            Path(args[args.index('--output')+1]).write_text('ready\n')
            self.assertEqual(args[args.index('--proxy')+1],'')
            self.assertNotIn('--location',args);self.assertNotIn('--insecure',args)
            return subprocess.CompletedProcess(args,0,json.dumps({'http_code':200,'time_namelookup':.01,'time_connect':.11,'time_appconnect':.25,'time_starttransfer':.4,'time_total':.41}).encode(),b'')
        entry={'id':1,'url':'https://ingress.test/healthz','expected_body':'ready'}
        with patch.object(p.subprocess,'run',side_effect=run):
            s=p.measure_ingress(entry)['measurement']
            self.assertTrue(s['body_ok']);self.assertIsNone(s['error']);self.assertEqual(s['tcp_ms'],100);self.assertEqual(s['tls_ms'],140)
            self.assertEqual(p.measure_ingress({**entry,'expected_body':'wrong'})['measurement']['error'],'body')
        with self.assertRaises(ValueError):p.measure_ingress({**entry,'url':'http://ingress.test'})
    def test_counters_use_physical_interface_deltas_and_handle_reset(self):
        cpu,net=m.rates((1,100,80,1000,2000),(3,200,130,251000,502000))
        self.assertEqual(cpu,50);self.assertEqual(net,{'in_speed':125000,'out_speed':250000})
        self.assertEqual(m.rates((1,100,80,1000,2000),(3,200,130,0,0))[1]['in_speed'],0)
    def test_ping_failure_and_missing_tool_are_different(self):
        with patch.object(m,'command',return_value=subprocess.CompletedProcess([],1,'3 packets transmitted, 0 received, 100% packet loss','')):
            self.assertEqual(m.ping_peer('10.1.0.2')['loss_percent'],100)
        with patch.object(m,'command',side_effect=FileNotFoundError()):
            self.assertIsNone(m.ping_peer('10.1.0.2')['loss_percent'])
        with patch.object(m,'command',return_value=subprocess.CompletedProcess([],0,'3 packets transmitted, 3 received, 0% packet loss\nrtt min/avg/max/mdev = 2.1/3.2/4.5/1.0 ms','')):
            self.assertEqual(m.ping_peer('10.1.0.2')['rtt_ms'],3.2)
    def test_monitor_rejects_interface_commands_and_redirects(self):
        data={'panel_url':'https://panel.test','machine_id':1,'token':'a'*32,'network_interface':'ens3','wireguard_interface':'wg-test','peers':['10.1.0.2']}
        m.validate(data)
        with self.assertRaises(ValueError):m.validate({**data,'network_interface':'ens3; reboot'})
        self.assertIsNone(m.NoRedirect().redirect_request(None,None,None,None,None,None))

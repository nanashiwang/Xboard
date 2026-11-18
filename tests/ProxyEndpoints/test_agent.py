import importlib.util
import unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('proxy_agent',Path(__file__).parents[2]/'.docker/proxy-endpoints/agent.py')
agent=importlib.util.module_from_spec(spec);spec.loader.exec_module(agent)
class AgentTest(unittest.TestCase):
    def fixture(self):
        return {'address':'216.36.108.173','server_time':1000,'lease_until':1120,'endpoints':[{'id':p,'port':p,'enabled':True,'revision':1,'expires_at':1060,'credentials':{'username':'cp_12345678','password':'abcdefgh12345678'}} for p in range(20001,20011)]}
    def test_whole_fixed_inventory_and_bounded_lease_required(self):
        data=self.fixture();self.assertEqual(10,len(agent.validate(data,data['address'])))
        data['lease_until']=1121
        with self.assertRaises(ValueError):agent.validate(data,data['address'])
        data=self.fixture();data['endpoints'][0]['port']=22
        with self.assertRaises(ValueError):agent.validate(data,data['address'])
        data=self.fixture();data['endpoints'][0]['expires_at']=999
        with self.assertRaises(ValueError):agent.validate(data,data['address'])
    def test_auth_is_loopback_only_and_private_targets_and_udp_are_denied(self):
        row=self.fixture()['endpoints'][0];config=agent.configuration(row)
        self.assertEqual('127.0.0.1',config['inbounds'][0]['listen']);self.assertEqual(21001,config['inbounds'][0]['listen_port'])
        self.assertEqual([row['credentials']],config['inbounds'][0]['users'])
        self.assertEqual('mixed',config['inbounds'][0]['type'])
        self.assertEqual('reject',config['route']['rules'][0]['action'])
        self.assertEqual('udp',config['route']['rules'][2]['network'])
    def test_disabled_snapshot_has_no_auth_and_cannot_select_arbitrary_unit(self):
        data=self.fixture();data['endpoints'][0].update(enabled=False,expires_at=0,credentials=None)
        agent.validate(data,data['address'])
        for port in [22,20011,'20001;reboot',True]:
            with self.assertRaises(ValueError):agent.service(port)
    def test_monotonic_deadline_is_bounded_by_both_expiry_and_control_lease(self):
        data=self.fixture();row=data['endpoints'][0]
        self.assertEqual(560,agent.grant_deadline(data,row,500))
        row['expires_at']=999999
        self.assertEqual(620,agent.grant_deadline(data,row,500))
        row['enabled']=False
        self.assertEqual(0,agent.grant_deadline(data,row,500))
if __name__=='__main__':unittest.main()

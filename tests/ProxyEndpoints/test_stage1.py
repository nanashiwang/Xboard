import runpy
import unittest
from pathlib import Path

stage1 = runpy.run_path(str(Path(__file__).parents[2] / '.docker/proxy-endpoints/stage1.py'))


class FixedRoutesTest(unittest.TestCase):
    def test_every_route_terminates_at_its_own_authenticated_port(self):
        routes = stage1['routes']()
        self.assertEqual(routes.count('location = '), 20)
        for key, host in stage1['HOSTS'].items():
            config = stage1['exit_config'](key)
            self.assertEqual(config['admissions'][0]['matchers'], [stage1['ENTRY']])
            for port, service in zip(stage1['PORTS'], config['services']):
                location = routes.split(f'location = /residential/v1/{key}/{port} {{')[1].split('location = ')[0]
                self.assertIn(f'proxy_pass https://{host}:{port + 3000}/ws;', location)
                self.assertIn('proxy_ssl_verify on;', location)
                self.assertEqual(service['addr'], f'{host}:{port + 3000}')
                self.assertEqual(service['admission'], 'stage1')
                self.assertEqual(service['forwarder']['nodes'][0]['addr'], f'{host}:{port}')

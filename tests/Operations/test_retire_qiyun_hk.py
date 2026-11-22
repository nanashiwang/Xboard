import json
from pathlib import Path
import runpy
import sqlite3
import unittest

retire = runpy.run_path(str(Path(__file__).resolve().parents[2] / '.docker/production/retire-qiyun-hk.py'))['remove']


class RetireHongKongTest(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript("""
            CREATE TABLE v2_server_machine(id INTEGER PRIMARY KEY, name);
            CREATE TABLE v2_server(id, name, host, machine_id, parent_id, type, dedicated_exit_id);
            CREATE TABLE v2_dedicated_exit(public_ip, shared_server_id, probe_server_id);
            CREATE TABLE residential_proxy_hosts(address);
            CREATE TABLE v2_node_probe(id, server_ids, expected_exits);
            CREATE TABLE v2_node_probe_ingress(id, machine_id, host, server_tunnels);
            INSERT INTO v2_server_machine VALUES(3,'七云香港｜103.24.217.171'),(12,'其他机器');
            INSERT INTO v2_server VALUES(325,'香港01｜1×','node.lumavia.fyi',NULL,338,'vless',NULL),
                (338,'__香港隧道后端|香港自建｜直连','103.24.217.171',3,NULL,'vless',NULL),
                (322,'美国10','node.lumavia.fyi',NULL,335,'vless',NULL),(335,'美国后端','other',12,NULL,'vless',NULL);
            INSERT INTO v2_node_probe VALUES(1,'[322,325]','{"322":"other","325":"103.24.217.171"}');
            INSERT INTO v2_node_probe_ingress VALUES(1,16,'node.lumavia.fyi','{"322":"keep","325":"drop"}');
        """)

    def test_remove_and_repeat(self):
        self.assertEqual(retire(self.db), {'deleted_machines': [3], 'deleted_nodes': [325, 338]})
        self.assertEqual(self.db.execute('SELECT id FROM v2_server ORDER BY id').fetchall(), [(322,), (335,)])
        self.assertEqual(self.db.execute('SELECT id FROM v2_server_machine').fetchall(), [(12,)])
        ids, exits = self.db.execute('SELECT server_ids, expected_exits FROM v2_node_probe').fetchone()
        self.assertEqual((json.loads(ids), json.loads(exits)), ([322], {'322': 'other'}))
        self.assertEqual(json.loads(self.db.execute('SELECT server_tunnels FROM v2_node_probe_ingress').fetchone()[0]),
                         {'322': 'keep'})
        self.assertEqual(retire(self.db), {'deleted_machines': [], 'deleted_nodes': []})

    def test_shared_backend_rejected(self):
        self.db.execute('UPDATE v2_server SET parent_id=338 WHERE id=322')
        self.db.commit()
        with self.assertRaisesRegex(ValueError, 'sharing'):
            retire(self.db)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM v2_server').fetchone()[0], 4)

    def test_probe_edit_rolled_back_on_ingress_conflict(self):
        self.db.execute("""UPDATE v2_node_probe_ingress SET server_tunnels='{"325":"only"}'""")
        self.db.commit()
        with self.assertRaisesRegex(ValueError, 'empty ingress'):
            retire(self.db)
        self.assertEqual(self.db.execute('SELECT server_ids FROM v2_node_probe').fetchone()[0], '[322,325]')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM v2_server_machine').fetchone()[0], 2)

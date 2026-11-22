import json
import runpy
import sqlite3
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REMOVE = runpy.run_path(str(ROOT / '.docker/production/retire-upstream-nodes.py'))['remove_nodes']
ALLOCATION = json.loads((ROOT / '.docker/upstream/allocation.json').read_text())


def database():
    db = sqlite3.connect(':memory:')
    db.executescript("""
        CREATE TABLE v2_server(id INTEGER PRIMARY KEY, machine_id, parent_id, server_port,
                               tags, type DEFAULT 'vless', dedicated_exit_id);
        CREATE TABLE v2_server_machine(id PRIMARY KEY, is_active, name, notes);
        CREATE TABLE v2_dedicated_exit(shared_server_id, probe_server_id);
        CREATE TABLE v2_node_probe(server_ids, expected_exits);
        CREATE TABLE v2_node_probe_ingress(machine_id, server_tunnels);
        INSERT INTO v2_server_machine VALUES(12,1,'其他',''),(21,1,'拓展转发｜第一阶段服务器','143.203.200.5；单独节点进程');
        INSERT INTO v2_server(id,machine_id) VALUES(335,12);
        INSERT INTO v2_server(id,parent_id) VALUES(322,335);
        INSERT INTO v2_dedicated_exit VALUES(335,322);
        INSERT INTO v2_node_probe VALUES('[322]','{"322":"ip"}');
        INSERT INTO v2_node_probe_ingress VALUES(3,'{"322":"peer"}');
    """)
    for r in ALLOCATION['routes']:
        db.execute('INSERT INTO v2_server(id,machine_id,server_port,tags) VALUES(?,21,?,?)',
                   (r['backend_id'], r['port'], json.dumps(['upstream-extension-backend', r['key']])))
        db.execute('INSERT INTO v2_server(id,parent_id,tags) VALUES(?,?,?)',
                   (r['public_id'], r['backend_id'], json.dumps(['upstream-extension-public', r['key']])))
    db.commit()
    return db


class RetireUpstreamNodes(unittest.TestCase):
    def test_removes_exact_pairs_and_disables_only_their_machine(self):
        db = database()
        self.addCleanup(db.close)
        self.assertEqual({'before': 84, 'deleted': 82, 'remaining_ids': [322,335]}, REMOVE(db, ALLOCATION))
        self.assertEqual([(12,1), (21,0)], [tuple(r) for r in db.execute('SELECT id,is_active FROM v2_server_machine ORDER BY id')])
        self.assertEqual(0, REMOVE(db, ALLOCATION)['deleted'])

    def test_remove_only_unused_registration_and_retry(self):
        db = database()
        self.addCleanup(db.close)
        with self.assertRaisesRegex(ValueError, 'still registered'):
            REMOVE(db, ALLOCATION, registration_only=True)
        self.assertEqual(84, db.execute('SELECT COUNT(*) FROM v2_server').fetchone()[0])
        REMOVE(db, ALLOCATION)
        for _ in range(2):
            self.assertEqual([322,335], REMOVE(db, ALLOCATION, registration_only=True)['remaining_ids'])
            self.assertEqual([12], [r[0] for r in db.execute('SELECT id FROM v2_server_machine')])
        self.assertEqual(0, REMOVE(db, ALLOCATION)['deleted'])

    def test_registration_stays_if_reused(self):
        for sql in ("UPDATE v2_server_machine SET name='new' WHERE id=21",
                    'UPDATE v2_server_machine SET is_active=1 WHERE id=21',
                    'UPDATE v2_node_probe_ingress SET machine_id=21',
                    'UPDATE v2_server SET machine_id=21 WHERE id=335'):
            with self.subTest(sql=sql):
                db = database()
                self.addCleanup(db.close)
                REMOVE(db, ALLOCATION)
                db.execute(sql)
                db.commit()
                with self.assertRaises(ValueError):
                    REMOVE(db, ALLOCATION, registration_only=True)
                self.assertTrue(db.execute('SELECT 1 FROM v2_server_machine WHERE id=21').fetchone())

    def test_blocks_changed_identity_references_and_partial_inventory(self):
        for mutation in (
            "UPDATE v2_server SET tags='[]' WHERE id=440",
            'UPDATE v2_server SET machine_id=21 WHERE id=335',
            'UPDATE v2_server SET parent_id=359 WHERE id=322',
            'UPDATE v2_dedicated_exit SET shared_server_id=359',
            "UPDATE v2_node_probe SET expected_exits='{\"360\":\"ip\"}'",
            "UPDATE v2_node_probe_ingress SET server_tunnels='{\"360\":\"peer\"}'",
            'DELETE FROM v2_server WHERE id=360',
            'DELETE FROM v2_server_machine WHERE id=21',
        ):
            with self.subTest(mutation=mutation):
                db = database()
                self.addCleanup(db.close)
                db.execute(mutation)
                db.commit()
                before = list(db.iterdump())
                with self.assertRaises(ValueError):
                    REMOVE(db, ALLOCATION)
                self.assertEqual(before, list(db.iterdump()))

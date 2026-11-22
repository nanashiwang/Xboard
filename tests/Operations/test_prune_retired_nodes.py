import json
from pathlib import Path
import runpy
import sqlite3
import unittest

module = runpy.run_path(str(Path(__file__).resolve().parents[2] / '.docker/production/prune-retired-nodes.py'))
cleanup = module['cleanup']


def fixture():
    db = sqlite3.connect(':memory:')
    db.executescript("""
        CREATE TABLE v2_server(id INTEGER PRIMARY KEY, parent_id, machine_id, dedicated_exit_id,
                               type DEFAULT 'vless', show DEFAULT 0, enabled DEFAULT 0, group_ids DEFAULT '[]');
        CREATE TABLE v2_node_probe(server_ids, expected_exits);
        CREATE TABLE v2_node_probe_ingress(id, server_tunnels);
        CREATE TABLE v2_dedicated_exit(id, plan_id DEFAULT 5, enabled DEFAULT 0,
                                      shared_server_id, probe_server_id, probe_id DEFAULT 1);
        CREATE TABLE v2_dedicated_assignment(exit_id);
        INSERT INTO v2_server(id,enabled,machine_id) VALUES (336,1,13), (337,1,14);
        INSERT INTO v2_server(id,parent_id,show) VALUES (323,336,1), (324,337,1);
        INSERT INTO v2_node_probe VALUES ('[323]', '{"323":"example"}');
        INSERT INTO v2_node_probe_ingress VALUES (1, '{"323":"keep","314":"retired"}');
    """)
    for source, backend, machine, alias, pool in module['RETIRED']:
        db.execute('INSERT INTO v2_server(id,parent_id) VALUES (?,?)', (source, backend))
        db.execute('INSERT INTO v2_server(id,machine_id) VALUES (?,?)', (backend, machine))
        if pool:
            db.execute('INSERT INTO v2_server(id,parent_id,dedicated_exit_id) VALUES (?,?,?)', (alias, backend, pool))
            db.execute('INSERT INTO v2_dedicated_exit(id,shared_server_id,probe_server_id) VALUES (?,?,?)',
                       (pool, backend, source))
    for alias, backend, pool, source in module['ALIAS_ONLY']:
        db.execute('INSERT INTO v2_server(id,parent_id,dedicated_exit_id) VALUES (?,?,?)', (alias, backend, pool))
        db.execute('INSERT INTO v2_dedicated_exit(id,shared_server_id,probe_server_id) VALUES (?,?,?)',
                   (pool, backend, source))
    db.commit()
    return db


class PruneRetiredNodesTest(unittest.TestCase):
    def test_delete_preserves_live_parents_and_pool_references(self):
        db = fixture()
        self.addCleanup(db.close)
        result = cleanup(db)
        self.assertEqual((38, 4), (len(result['deleted']), result['remaining']))
        self.assertEqual({323, 324, 336, 337}, {r[0] for r in db.execute('SELECT id FROM v2_server')})
        self.assertEqual({'323': 'keep'}, json.loads(db.execute('SELECT server_tunnels FROM v2_node_probe_ingress').fetchone()[0]))
        self.assertEqual([(15,336,323), (16,337,324)], [tuple(r) for r in db.execute(
            'SELECT id,shared_server_id,probe_server_id FROM v2_dedicated_exit WHERE shared_server_id IS NOT NULL ORDER BY id')])
        self.assertEqual([], cleanup(db)['deleted'])

    def test_refuses_live_references_or_identity_drift_without_partial_cleanup(self):
        for sql in (
            'UPDATE v2_server SET enabled=1 WHERE id=147',
            "UPDATE v2_server SET group_ids='[1]' WHERE id=327",
            'UPDATE v2_server SET parent_id=147 WHERE id=323',
            "UPDATE v2_node_probe SET expected_exits='{\"148\":\"used\"}'",
            'INSERT INTO v2_dedicated_assignment VALUES (6)',
            'UPDATE v2_dedicated_exit SET enabled=1 WHERE id=15',
            'UPDATE v2_server SET machine_id=3 WHERE id=147',
        ):
            with self.subTest(sql=sql):
                db = fixture()
                self.addCleanup(db.close)
                db.execute(sql)
                db.commit()
                with self.assertRaises(ValueError):
                    cleanup(db)
                self.assertEqual(42, db.execute('SELECT COUNT(*) FROM v2_server').fetchone()[0])
                self.assertIn('314', db.execute('SELECT server_tunnels FROM v2_node_probe_ingress').fetchone()[0])

import importlib.util
import json
import sqlite3
import unittest
from pathlib import Path

path = Path(__file__).resolve().parents[2] / '.docker/production/prune-retired-machines.py'
spec = importlib.util.spec_from_file_location('prune_machines', path)
cleanup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleanup)


class RetiredMachinesTest(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript("""
            CREATE TABLE v2_server_machine(id INTEGER PRIMARY KEY, name, notes, last_seen_at, load_status, is_active DEFAULT 1);
            CREATE TABLE v2_server(id, parent_id, show, enabled, machine_id, host);
            CREATE TABLE v2_node_probe_ingress(machine_id, host);
            CREATE TABLE v2_server_machine_load_history(machine_id REFERENCES v2_server_machine ON DELETE CASCADE, recorded_at);
            CREATE TABLE residential_proxy_hosts(address);
            CREATE TABLE v2_node_probe(expected_exits);
            CREATE TABLE v2_dedicated_exit(id, public_ip, enabled, standby DEFAULT 0, shared_server_id, probe_server_id);
            CREATE TABLE v2_dedicated_assignment(exit_id);
            INSERT INTO v2_server_machine VALUES(3, '香港', NULL, 1, NULL, 1);
            INSERT INTO v2_server VALUES(338, 0, 0, 1, 3, '103.24.217.171'), (325, 338, 1, 0, NULL, 'ingress');
            INSERT INTO v2_server_machine_load_history VALUES(3, 1), (4, 2);
        """)
        self.db.executemany('INSERT INTO v2_server_machine VALUES(?,?,?,?,?,1)', [
            (sid, '七云美国｜' + ip, '到期 2026-10-28', cleanup.CUTOFF-1,
             json.dumps({'updated_at': cleanup.CUTOFF-1})) for sid, ip in cleanup.RETIRED.items()])
        self.db.commit()

    def test_prune_readback_and_retry(self):
        self.assertEqual(cleanup.prune(self.db)['deleted'], list(cleanup.RETIRED))
        receipt = cleanup.readback(self.db)
        self.assertEqual(receipt['remaining'], 1)
        self.assertEqual(receipt['hk_nodes_id_parent_show_enabled'], [(325, 338, 1, 0), (338, 0, 0, 1)])
        self.assertEqual(self.db.execute('SELECT * FROM v2_server_machine_load_history').fetchall(), [(3, 1)])
        self.assertEqual(cleanup.prune(self.db)['deleted'], [])

    def test_keep_current_dependencies_or_changed_identity(self):
        ips = cleanup.RETIRED
        self.db.execute('UPDATE v2_server_machine SET name=? WHERE id=4', ('other',))
        self.db.execute('UPDATE v2_server_machine SET last_seen_at=? WHERE id=5', (cleanup.CUTOFF,))
        self.db.execute("INSERT INTO v2_server(machine_id) VALUES(6)")
        self.db.execute("INSERT INTO v2_node_probe_ingress(machine_id) VALUES(7)")
        self.db.execute("INSERT INTO residential_proxy_hosts VALUES(?)", (ips[8],))
        self.db.execute("INSERT INTO v2_node_probe VALUES(?)", (json.dumps({'100': ips[9]}),))
        self.db.execute("INSERT INTO v2_dedicated_exit VALUES(1,?,0,0,NULL,NULL)", (ips[10],))
        self.db.execute("INSERT INTO v2_dedicated_assignment VALUES(1)")
        self.db.execute('INSERT INTO v2_server_machine_load_history VALUES(11,?)', (cleanup.CUTOFF,))
        self.db.commit()
        self.assertEqual(set(cleanup.prune(self.db)['kept']), set(ips))
        self.assertEqual(cleanup.readback(self.db)['remaining'], 9)

    def add_cn2_windows(self):
        self.db.executemany('INSERT INTO v2_server_machine VALUES(?,?,?,?,?,?)', [
            (15, '七云美国CN2｜154.44.1.123', '到期 2026-11-11', cleanup.CN2_CUTOFF-1,
             json.dumps({'updated_at': cleanup.CN2_CUTOFF-1}), 1),
            (16, '七云Windows｜216.36.124.7', '到期2026-10-20', None, None, 0),
        ])
        self.db.execute("INSERT INTO v2_dedicated_exit VALUES(17,'154.44.1.123',0,0,NULL,NULL)")
        self.db.commit()

    def test_cn2_and_disabled_windows_separate_batch(self):
        self.add_cn2_windows()
        self.assertEqual(cleanup.prune(self.db, cleanup.CN2_WINDOWS)['deleted'], [15, 16])
        self.assertEqual(cleanup.machine_ids(self.db), {3, *cleanup.RETIRED})
        self.assertEqual(cleanup.prune(self.db, cleanup.CN2_WINDOWS)['deleted'], [])
        self.assertEqual(self.db.execute('SELECT id FROM v2_dedicated_exit').fetchall(), [(17,)])

    def test_keep_reassigned_exit_or_reenabled_windows(self):
        self.add_cn2_windows()
        self.db.execute('UPDATE v2_dedicated_exit SET standby=1 WHERE id=17')
        self.db.execute('UPDATE v2_server_machine SET is_active=1 WHERE id=16')
        self.db.commit()
        self.assertEqual(set(cleanup.prune(self.db, cleanup.CN2_WINDOWS)['kept']), {15, 16})

    def test_failure_rolls_back_prior_deletes(self):
        self.db.execute("""CREATE TRIGGER abort_last BEFORE DELETE ON v2_server_machine WHEN OLD.id=11
            BEGIN SELECT RAISE(ABORT, 'test failure'); END""")
        with self.assertRaises(sqlite3.IntegrityError):
            cleanup.prune(self.db)
        self.assertEqual(cleanup.readback(self.db)['remaining'], 9)

import runpy
import sqlite3
import unittest
from pathlib import Path

MODULE = runpy.run_path(str(Path(__file__).resolve().parents[2] / '.docker/production/retire-extension-probe.py'))


class RetireExtensionProbeTest(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript("""
            CREATE TABLE v2_node_probe (id INTEGER PRIMARY KEY, name TEXT, location TEXT);
            CREATE TABLE v2_dedicated_exit (probe_id INTEGER);
            INSERT INTO v2_dedicated_exit VALUES (1);
            INSERT INTO v2_node_probe VALUES (1, 'nas', '家庭网络 / NAS'),
                (2, '拓展线路探针（面板服务器）', '面板服务器 · 美国');
        """)
        for suffix in MODULE['TABLES']:
            self.db.executescript(f"""
                CREATE TABLE v2_node_probe_{suffix} (probe_id INTEGER);
                INSERT INTO v2_node_probe_{suffix} VALUES (1), (2);
            """)

    def test_removes_only_target_and_can_retry(self):
        for _ in range(2):
            MODULE['remove_registration'](self.db)
        self.assertEqual([(1,)], self.db.execute('SELECT id FROM v2_node_probe').fetchall())
        for suffix in MODULE['TABLES']:
            self.assertEqual([(1,)], self.db.execute(f'SELECT probe_id FROM v2_node_probe_{suffix}').fetchall())

    def test_refuses_changed_identity_and_dedicated_dependency(self):
        for sql in ["UPDATE v2_node_probe SET name = 'replacement' WHERE id = 2",
                    'INSERT INTO v2_dedicated_exit VALUES (2)']:
            with self.subTest(sql=sql):
                with self.db:
                    self.db.execute(sql)
                with self.assertRaises(RuntimeError):
                    MODULE['remove_registration'](self.db)
                self.assertEqual(2, self.db.execute('SELECT COUNT(*) FROM v2_node_probe_sample').fetchone()[0])
                with self.db:
                    self.db.execute('UPDATE v2_node_probe SET name = ? WHERE id = 2', (MODULE['NAME'],))

    def test_database_error_rolls_back_samples(self):
        self.db.execute('DROP TABLE v2_node_probe_event')
        with self.assertRaises(sqlite3.OperationalError):
            MODULE['remove_registration'](self.db)
        self.assertEqual(2, self.db.execute('SELECT COUNT(*) FROM v2_node_probe_sample').fetchone()[0])

import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest


class KnowledgeSyncTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copy(Path(__file__).resolve().parents[2] / '.docker/knowledge/sync.py', self.root)
        (self.root / 'articles').mkdir()
        (self.root / 'articles/downloads.md').write_text('new guide')
        (self.root / 'manifest.json').write_text(json.dumps({'articles': [
            {'id': 1, 'title': 'unrelated', 'file': 'articles/missing.md', 'expected_body_sha256': 'unrelated'},
            {'id': 5, 'title': 'downloads', 'file': 'articles/downloads.md',
             'expected_body_sha256': hashlib.sha256(b'old guide').hexdigest()},
        ]}))
        self.database = self.root / 'test.sqlite'
        with sqlite3.connect(self.database) as db:
            db.execute('CREATE TABLE v2_knowledge (id INTEGER, title TEXT, body TEXT, updated_at INTEGER, show INTEGER)')
            db.executemany('INSERT INTO v2_knowledge VALUES (?, ?, ?, ?, ?)', [
                (5, 'downloads', 'old guide', 1, 1), (9, 'keep', 'unrelated', 2, 0),
            ])

    def run_sync(self, *args):
        return subprocess.run([sys.executable, str(self.root / 'sync.py'), '--database', str(self.database), *args], capture_output=True, text=True)

    def rows(self):
        with sqlite3.connect(self.database) as db:
            return db.execute('SELECT * FROM v2_knowledge ORDER BY id').fetchall()

    def test_preview_does_not_write_and_does_not_read_unselected_sources(self):
        before = self.rows()
        result = self.run_sync('--article-id', '5')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(before, self.rows())

    def test_selected_update_preserves_other_rows_metadata_and_is_idempotent(self):
        args = ['--article-id', '5', '--apply', '--backup-dir', str(self.root / 'backups')]
        before = self.rows()
        result = self.run_sync(*args)
        self.assertEqual(0, result.returncode, result.stderr)
        after = self.rows()
        self.assertEqual('new guide', after[0][2])
        self.assertEqual(before[0][0:2], after[0][0:2])
        self.assertEqual(before[0][4], after[0][4])
        self.assertEqual(before[1], after[1])
        backups = list((self.root / 'backups').glob('*.json'))
        self.assertEqual(1, len(backups))
        self.assertEqual('old guide', json.loads(backups[0].read_text())['articles'][0]['before']['body'])
        self.assertEqual(0, self.run_sync(*args).returncode)
        self.assertEqual(after, self.rows())
        self.assertEqual(backups, list((self.root / 'backups').glob('*.json')))

    def test_conflict_is_rejected_without_changes_or_backup(self):
        with sqlite3.connect(self.database) as db:
            db.execute("UPDATE v2_knowledge SET body = 'admin edit' WHERE id = 5")
        before = self.rows()
        result = self.run_sync('--article-id', '5', '--apply', '--backup-dir', str(self.root / 'backups'))
        self.assertNotEqual(0, result.returncode)
        self.assertEqual(before, self.rows())
        self.assertFalse((self.root / 'backups').exists())

    def test_unknown_id_is_rejected(self):
        before = self.rows()
        self.assertNotEqual(0, self.run_sync('--article-id', '999').returncode)
        self.assertEqual(before, self.rows())


if __name__ == '__main__':
    unittest.main()

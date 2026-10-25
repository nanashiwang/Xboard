import importlib.util
from pathlib import Path
import sqlite3
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[2] / ".docker/production/backup-database.py"
SPEC = importlib.util.spec_from_file_location("database_backup", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class DatabaseBackupTest(unittest.TestCase):
    def test_live_wal_snapshot_is_complete_private_and_does_not_replace_previous_backup(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "live.sqlite"
            directory = Path(root) / "backups"
            with sqlite3.connect(source) as live:
                live.execute("PRAGMA journal_mode=WAL")
                live.execute("CREATE TABLE example (value TEXT)")
                live.execute("INSERT INTO example VALUES ('committed')")
                live.commit()
                first = MODULE.backup_database(source, directory)
                live.execute("INSERT INTO example VALUES ('later')")
                live.commit()
                second = MODULE.backup_database(source, directory)
                self.assertNotEqual(first, second)
                for path, count in [(first, 1), (second, 2)]:
                    self.assertEqual(path.stat().st_mode & 0o777, 0o600)
                    with sqlite3.connect(path) as snapshot:
                        self.assertEqual(snapshot.execute("SELECT count(*) FROM example").fetchone()[0], count)
            self.assertEqual(directory.stat().st_mode & 0o777, 0o700)

    def test_missing_or_corrupt_source_fails_without_leaving_a_backup(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "live.sqlite"
            directory = Path(root) / "backups"
            with self.assertRaises(FileNotFoundError):
                MODULE.backup_database(source, directory)
            self.assertFalse(source.exists())
            source.write_bytes(b"not a SQLite database")
            with self.assertRaises(sqlite3.DatabaseError):
                MODULE.backup_database(source, directory)
            self.assertEqual(list(directory.iterdir()), [])

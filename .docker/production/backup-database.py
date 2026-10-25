"""Create a private, consistent SQLite snapshot before production migrations."""
import os
from pathlib import Path
import sqlite3
import sys
import tempfile


def backup_database(source: Path, directory: Path) -> Path:
    source = source.resolve(strict=True)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, filename = tempfile.mkstemp(prefix="before-deploy-", suffix=".sqlite", dir=directory)
    os.close(descriptor)
    target = Path(filename)
    try:
        with sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=30) as live:
            with sqlite3.connect(target) as snapshot:
                live.backup(snapshot)
                if snapshot.execute("PRAGMA integrity_check").fetchall() != [("ok",)]:
                    raise RuntimeError("Database snapshot integrity check failed")
        return target
    except Exception:
        target.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    print("Verified database backup:", backup_database(Path(sys.argv[1]), Path(sys.argv[2])))

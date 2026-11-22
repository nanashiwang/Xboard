"""Retire only the panel host's extension monitor, using the production SQLite database."""
import json
import sqlite3
import subprocess
import time
from pathlib import Path

DATABASE = Path('/root/Xboard/.docker/.data/database.sqlite')
SERVICE = 'xboard-extension-probe.service'
TABLES = ('sample', 'ingress_sample', 'hour', 'event', 'state')
NAME = '拓展线路探针（面板服务器）'


def check_target(db):
    row = db.execute('SELECT name, location FROM v2_node_probe WHERE id = 2').fetchone()
    if row is not None and row != (NAME, '面板服务器 · 美国'):
        raise RuntimeError(f'Probe 2 identity differs: {row!r}')
    if db.execute('SELECT 1 FROM v2_dedicated_exit WHERE probe_id = 2 LIMIT 1').fetchone():
        raise RuntimeError('A dedicated exit references probe 2')
    return row is not None


def remove_registration(db):
    with db:
        db.execute('BEGIN IMMEDIATE')
        if not check_target(db):
            return
        for suffix in TABLES:
            db.execute(f'DELETE FROM v2_node_probe_{suffix} WHERE probe_id = 2')
        db.execute('DELETE FROM v2_node_probe WHERE id = 2')


def unit_property(unit, name):
    return subprocess.check_output(['systemctl', 'show', unit, '-p', name, '--value'], text=True).strip()


def main():
    with sqlite3.connect(DATABASE.resolve(strict=True).as_uri() + '?mode=rw', uri=True, timeout=30) as db:
        check_target(db)
        subprocess.run(['systemctl', 'disable', '--now', SERVICE], check=True)
        remove_registration(db)
        if unit_property(SERVICE, 'ActiveState') != 'inactive' or unit_property(SERVICE, 'UnitFileState') != 'disabled':
            raise RuntimeError('Extension sampler still running or enabled')
        if check_target(db):
            raise RuntimeError('Probe registration still present')
        # A sample written after removal verifies that the independent NAS agent still reports.
        removed_at = int(time.time())
        for _ in range(45):
            latest = db.execute('SELECT MAX(checked_at) FROM v2_node_probe_sample WHERE probe_id = 1').fetchone()[0]
            nas = db.execute('SELECT name, enabled, last_seen_at, server_ids FROM v2_node_probe WHERE id = 1').fetchone()
            if nas and nas[1] and latest and latest > removed_at and nas[2] and nas[2] > removed_at:
                print(json.dumps({'remaining_probe_ids': [r[0] for r in db.execute('SELECT id FROM v2_node_probe ORDER BY id')],
                                  'nas_name': nas[0], 'nas_nodes': len(json.loads(nas[3])),
                                  'nas_sample_at': latest, 'nas_seen_at': nas[2], 'removed_at': removed_at,
                                  'extension_service': 'disabled/inactive',
                                  'guard_timer': unit_property('xboard-upstream-guard.timer', 'ActiveState')}, ensure_ascii=False))
                return
            time.sleep(5)
        raise RuntimeError(f'Removal complete, no new NAS heartbeat and sample since {removed_at}')


if __name__ == '__main__':
    main()

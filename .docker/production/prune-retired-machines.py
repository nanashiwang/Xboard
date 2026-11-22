"""Remove only the eight retired Qiyun US panel registrations from October 2026."""
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DATABASE = Path('/root/Xboard/.docker/.data/database.sqlite')
RETIRED = {
    4: '192.204.56.222', 5: '192.220.36.213', 6: '192.220.50.110', 7: '192.220.25.84',
    8: '216.36.124.194', 9: '38.244.38.191', 10: '216.36.124.220', 11: '216.36.112.198',
}
CUTOFF = int(datetime(2026, 11, 1, tzinfo=timezone.utc).timestamp())


def retain_reason(db, sid, ip, machine):
    name, notes, heartbeat, load_at = machine
    if name != '七云美国｜' + ip or '2026-10-28' not in (notes or ''):
        return 'identity or expiry changed'
    if not heartbeat or not load_at or max(heartbeat, load_at) >= CUTOFF:
        return 'activity outside retirement window'
    checks = [
        ('node', 'SELECT 1 FROM v2_server WHERE machine_id=? OR host=?', (sid, ip)),
        ('ingress', 'SELECT 1 FROM v2_node_probe_ingress WHERE machine_id=? OR host=?', (sid, ip)),
        ('load history', 'SELECT 1 FROM v2_server_machine_load_history WHERE machine_id=? AND recorded_at>=?', (sid, CUTOFF)),
        ('proxy inventory', 'SELECT 1 FROM residential_proxy_hosts WHERE address=?', (ip,)),
        ('probe exit', 'SELECT 1 FROM v2_node_probe, json_each(expected_exits) WHERE json_each.value=?', (ip,)),
        ('dedicated exit', '''SELECT 1 FROM v2_dedicated_exit e WHERE public_ip=? AND
            (enabled OR shared_server_id IS NOT NULL OR probe_server_id IS NOT NULL OR
             EXISTS (SELECT 1 FROM v2_dedicated_assignment a WHERE a.exit_id=e.id))''', (ip,)),
    ]
    for reason, sql, args in checks:
        if db.execute(sql, args).fetchone():
            return reason
    return None


def machine_ids(db):
    return {r[0] for r in db.execute('SELECT id FROM v2_server_machine')}


def prune(db):
    db.execute('PRAGMA foreign_keys=ON')
    with db:
        db.execute('BEGIN IMMEDIATE')
        before = machine_ids(db)
        deleted, kept = [], {}
        for sid, ip in RETIRED.items():
            row = db.execute("""SELECT name, notes, last_seen_at, json_extract(load_status, '$.updated_at')
                                FROM v2_server_machine WHERE id=?""", (sid,)).fetchone()
            if row is None:
                continue
            reason = retain_reason(db, sid, ip, row)
            if reason:
                kept[sid] = reason
                continue
            db.execute('DELETE FROM v2_server_machine WHERE id=?', (sid,))
            deleted.append(sid)
        if machine_ids(db) != before.difference(deleted):
            raise RuntimeError('Unexpected change to machine inventory')
        return {'before': len(before), 'deleted': deleted, 'kept': kept}


def readback(db):
    with db:
        db.execute('BEGIN')
        ids = machine_ids(db)
        hk = db.execute('SELECT last_seen_at FROM v2_server_machine WHERE id=3').fetchone()
        nodes = db.execute('''SELECT id, parent_id, show, enabled FROM v2_server WHERE machine_id=3
            OR parent_id IN (SELECT id FROM v2_server WHERE machine_id=3) ORDER BY id''').fetchall()
        return {'remaining': len(ids), 'listed_us': sorted(ids.intersection(RETIRED)),
                'hk_last_seen': hk[0] if hk else None, 'hk_nodes_id_parent_show_enabled': nodes}


if __name__ == '__main__':
    uri = DATABASE.resolve(strict=True).as_uri()
    with sqlite3.connect(uri + '?mode=rw', uri=True, timeout=30) as writer:
        print(json.dumps(prune(writer)))
    with sqlite3.connect(uri + '?mode=ro', uri=True, timeout=30) as reader:
        print(json.dumps(readback(reader)))

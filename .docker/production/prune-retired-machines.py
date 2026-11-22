"""Remove only the selected batch of retired Qiyun panel registrations."""
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DATABASE = Path('/root/Xboard/.docker/.data/database.sqlite')
RETIRED = {
    4: '192.204.56.222', 5: '192.220.36.213', 6: '192.220.50.110', 7: '192.220.25.84',
    8: '216.36.124.194', 9: '38.244.38.191', 10: '216.36.124.220', 11: '216.36.112.198',
}
CN2_WINDOWS = {15: '154.44.1.123', 16: '216.36.124.7'}
CN2_CUTOFF = int(datetime(2026, 11, 16, tzinfo=timezone.utc).timestamp())
CUTOFF = int(datetime(2026, 11, 1, tzinfo=timezone.utc).timestamp())


def retain_reason(db, sid, ip, machine):
    name, notes, heartbeat, load_at, active = machine
    prefix, expiry, cutoff = '七云美国', '2026-10-28', CUTOFF
    if sid == 15:
        prefix, expiry, cutoff = '七云美国CN2', '2026-11-11', CN2_CUTOFF
    elif sid == 16:
        prefix, expiry, cutoff = '七云Windows', '2026-10-20', 0
        # This disabled registration never reported to the panel.
        if active or heartbeat or load_at:
            return 'Windows registration has activity or is enabled'
    if name != prefix + '｜' + ip or expiry not in (notes or ''):
        return 'identity or expiry changed'
    if sid != 16 and (not heartbeat or not load_at or max(heartbeat, load_at) >= cutoff):
        return 'activity outside retirement window'
    checks = [
        ('node', 'SELECT 1 FROM v2_server WHERE machine_id=? OR host=?', (sid, ip)),
        ('ingress', 'SELECT 1 FROM v2_node_probe_ingress WHERE machine_id=? OR host=?', (sid, ip)),
        ('load history', 'SELECT 1 FROM v2_server_machine_load_history WHERE machine_id=? AND recorded_at>=?', (sid, cutoff)),
        ('proxy inventory', 'SELECT 1 FROM residential_proxy_hosts WHERE address=?', (ip,)),
        ('probe exit', 'SELECT 1 FROM v2_node_probe, json_each(expected_exits) WHERE json_each.value=?', (ip,)),
        ('dedicated exit', '''SELECT 1 FROM v2_dedicated_exit e WHERE public_ip=? AND
            (enabled OR standby OR shared_server_id IS NOT NULL OR probe_server_id IS NOT NULL OR
             EXISTS (SELECT 1 FROM v2_dedicated_assignment a WHERE a.exit_id=e.id))''', (ip,)),
    ]
    for reason, sql, args in checks:
        if db.execute(sql, args).fetchone():
            return reason
    return None


def machine_ids(db):
    return {r[0] for r in db.execute('SELECT id FROM v2_server_machine')}


def prune(db, targets=RETIRED):
    db.execute('PRAGMA foreign_keys=ON')
    with db:
        db.execute('BEGIN IMMEDIATE')
        before = machine_ids(db)
        deleted, kept = [], {}
        for sid, ip in targets.items():
            row = db.execute("""SELECT name, notes, last_seen_at, json_extract(load_status, '$.updated_at'), is_active
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
    if sys.argv[1:] not in ([], ['--cn2-windows']):
        raise SystemExit('Expected no arguments or --cn2-windows')
    targets = CN2_WINDOWS if sys.argv[1:] else RETIRED
    uri = DATABASE.resolve(strict=True).as_uri()
    with sqlite3.connect(uri + '?mode=rw', uri=True, timeout=30) as writer:
        print(json.dumps(prune(writer, targets)))
    with sqlite3.connect(uri + '?mode=ro', uri=True, timeout=30) as reader:
        if targets is RETIRED:
            print(json.dumps(readback(reader)))
        else:
            reader.execute('BEGIN')
            remaining = machine_ids(reader)
            listed = sorted(remaining.intersection(targets))
            nodes = [r[0] for r in reader.execute('SELECT id FROM v2_server ORDER BY id')]
            print(json.dumps(dict(remaining=len(remaining), listed_targets=listed, node_ids=nodes)))
            if listed:
                raise SystemExit('Requested registrations still present; see retention reasons')

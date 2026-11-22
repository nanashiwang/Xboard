"""Retire the Qiyun Hong Kong machine and its only public/backend pair."""
import json
import sqlite3
from pathlib import Path

DATABASE = Path('/root/Xboard/.docker/.data/database.sqlite')
IP = '103.24.217.171'


def require(condition, message):
    if not condition:
        raise ValueError(message)


def remove(db):
    db.execute('PRAGMA foreign_keys=ON')
    with db:
        db.execute('BEGIN IMMEDIATE')
        machine = db.execute('SELECT name FROM v2_server_machine WHERE id=3').fetchone()
        nodes = db.execute('''SELECT id, name, host, machine_id, parent_id, type, dedicated_exit_id
            FROM v2_server WHERE id IN (325,338) OR parent_id IN (325,338) OR machine_id=3 OR host=?
            ORDER BY id''', (IP,)).fetchall()
        if machine or nodes:
            require(machine == ('七云香港｜' + IP,), 'Machine 3 identity changed')
            require(nodes == [
                (325, '香港01｜1×', 'node.lumavia.fyi', None, 338, 'vless', None),
                (338, '__香港隧道后端|香港自建｜直连', IP, 3, None, 'vless', None),
            ], 'Node identity or sharing changed')

        require(not db.execute('''SELECT 1 FROM v2_dedicated_exit WHERE public_ip=?
            OR shared_server_id IN (325,338) OR probe_server_id IN (325,338)''', (IP,)).fetchone(),
                'Dedicated pool depends on this exit')
        require(not db.execute('SELECT 1 FROM residential_proxy_hosts WHERE address=?', (IP,)).fetchone(),
                'Address in residential inventory')
        require(not db.execute('SELECT 1 FROM v2_node_probe_ingress WHERE machine_id=3 OR host=?', (IP,)).fetchone(),
                'Machine also provides monitored ingress')

        for probe, raw_ids, raw_exits in db.execute('SELECT id, server_ids, expected_exits FROM v2_node_probe').fetchall():
            ids = json.loads(raw_ids)
            exits = json.loads(raw_exits or '{}') or {}
            kept = [n for n in ids if int(n) not in (325, 338)]
            kept_exits = {k: v for k, v in exits.items() if k not in ('325', '338')}
            require(IP not in kept_exits.values(), 'Another probe target expects the Hong Kong exit')
            if ids != kept or exits != kept_exits:
                require(kept, 'Removing this route would leave an empty probe')
                db.execute('UPDATE v2_node_probe SET server_ids=?, expected_exits=? WHERE id=?',
                           (json.dumps(kept), json.dumps(kept_exits), probe))

        for entry, raw in db.execute('SELECT id, server_tunnels FROM v2_node_probe_ingress').fetchall():
            tunnels = json.loads(raw)
            kept = {k: v for k, v in tunnels.items() if k not in ('325', '338')}
            if kept != tunnels:
                require(kept, 'Removing this route would leave an empty ingress')
                db.execute('UPDATE v2_node_probe_ingress SET server_tunnels=? WHERE id=?', (json.dumps(kept), entry))

        if nodes:
            # Remove the child first so foreign-key actions cannot detach a retained node.
            db.execute('DELETE FROM v2_server WHERE id=325')
            db.execute('DELETE FROM v2_server WHERE id=338')
            db.execute('DELETE FROM v2_server_machine WHERE id=3')
        return {'deleted_machines': [3] if machine else [], 'deleted_nodes': [325, 338] if nodes else []}


if __name__ == '__main__':
    uri = DATABASE.resolve(strict=True).as_uri()
    with sqlite3.connect(uri + '?mode=rw', uri=True, timeout=30) as db:
        receipt = remove(db)
    with sqlite3.connect(uri + '?mode=ro', uri=True, timeout=30) as db:
        db.execute('BEGIN')
        machines = [r[0] for r in db.execute('SELECT id FROM v2_server_machine ORDER BY id')]
        nodes = [r[0] for r in db.execute('SELECT id FROM v2_server ORDER BY id')]
        require(3 not in machines and {325, 338}.isdisjoint(nodes), 'Readback found a retired record')
        print(json.dumps(dict(receipt, remaining_machines=len(machines), remaining_node_ids=nodes)))

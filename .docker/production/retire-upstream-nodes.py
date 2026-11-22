"""Remove the 41 explicitly retired third-party routes from the panel host."""
import json
import sqlite3
import subprocess
from pathlib import Path

DATABASE = Path('/root/Xboard/.docker/.data/database.sqlite')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def remove_nodes(db, allocation):
    db.row_factory = sqlite3.Row
    routes = allocation['routes']
    require(allocation['machine_id'] == 21 and len(routes) == 41, 'Unexpected allocation')
    targets = set()
    for n, route in enumerate(routes, 1):
        require((route['key'], route['backend_id'], route['public_id'], route['port']) ==
                (f'U{n:02d}', 357 + 2*n, 358 + 2*n, 37000 + n), 'Allocation identity changed')
        targets.update([route['backend_id'], route['public_id']])

    def all_nodes():
        return {r['id']: dict(r) for r in db.execute('SELECT * FROM v2_server')}

    with db:
        db.execute('BEGIN IMMEDIATE')
        nodes = all_nodes()
        remaining = {i: row for i, row in nodes.items() if i not in targets}
        for row in remaining.values():
            require(row['parent_id'] not in targets and row['machine_id'] != 21,
                    'A retained node uses the retired machine or a retired parent')
        present = targets.intersection(nodes)
        if present:
            require(present == targets, 'Partial or changed third-party inventory')
            for route in routes:
                backend, public = nodes[route['backend_id']], nodes[route['public_id']]
                require(backend['machine_id'] == 21 and not backend['parent_id'] and
                        int(backend['server_port']) == route['port'] and
                        not public['machine_id'] and public['parent_id'] == backend['id'],
                        f"Machine or parent changed for {route['key']}")
                for node, role in [(public, 'public'), (backend, 'backend')]:
                    tags = set(json.loads(node['tags']))
                    require({f'upstream-extension-{role}', route['key']} <= tags and
                            node['type'] == 'vless' and not node['dedicated_exit_id'],
                            f"Node {node['id']} identity changed")
        for row in db.execute('SELECT shared_server_id, probe_server_id FROM v2_dedicated_exit'):
            require(targets.isdisjoint(tuple(row)), 'Dedicated exit references a third-party node')
        for row in db.execute('SELECT server_ids, expected_exits FROM v2_node_probe'):
            ids = set(map(int, json.loads(row[0]))) | set(map(int, json.loads(row[1] or '{}') or {}))
            require(targets.isdisjoint(ids), 'A probe still references third-party nodes')
        for row in db.execute('SELECT machine_id, server_tunnels FROM v2_node_probe_ingress'):
            require(row[0] != 21 and targets.isdisjoint(map(int, json.loads(row[1]))),
                    'An ingress still uses the retired machine or nodes')

        if present:
            db.executemany('DELETE FROM v2_server WHERE id=?', [(i,) for i in sorted(targets)])
            updated = db.execute('UPDATE v2_server_machine SET is_active=0 WHERE id=21')
            require(updated.rowcount == 1, 'Machine registration missing')
        require(all_nodes() == remaining, 'Retained node configuration changed')
        machine = db.execute('SELECT is_active FROM v2_server_machine WHERE id=21').fetchone()
        require(machine is not None and machine[0] == 0, 'Unexpected machine state')
        return {'before': len(nodes), 'deleted': len(present), 'remaining_ids': sorted(remaining)}


if __name__ == '__main__':
    allocation = json.loads(Path(__file__).with_name('allocation.json').read_text())
    with sqlite3.connect(DATABASE.resolve(strict=True).as_uri() + '?mode=rw', uri=True, timeout=30) as db:
        db.execute('PRAGMA foreign_keys=ON')
        result = remove_nodes(db, allocation)
    timer = 'xboard-upstream-guard.timer'
    subprocess.run(['systemctl', 'disable', '--now', timer], check=True)
    subprocess.run(['systemctl', 'stop', 'xboard-upstream-guard.service'], check=True)
    for prop, expected in [('ActiveState','inactive'), ('UnitFileState','disabled')]:
        value = subprocess.check_output(['systemctl','show',timer,'-p',prop,'--value'], text=True).strip()
        require(value == expected, f'Guard {prop} is {value}')
    print(json.dumps(dict(result, guard='disabled/inactive', machine_21='inactive')))

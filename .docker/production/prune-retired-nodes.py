"""One-time cleanup of the two retired US node sets, verified on 2026-11-22."""
import json
import sqlite3
from pathlib import Path

DATABASE = Path('/root/Xboard/.docker/.data/database.sqlite')
# Source, backend, machine, fixed alias, pool. The final three pairs were duplicate CF entries.
RETIRED = (
    (148, 147, 2, 352, 18),
    (314, 327, 4, 340, 6),
    (315, 328, 5, 341, 7),
    (316, 329, 6, 342, 8),
    (317, 330, 7, 343, 9),
    (318, 331, 8, 344, 10),
    (319, 332, 9, 345, 11),
    (320, 333, 10, 346, 12),
    (321, 334, 11, 347, 13),
    (326, 339, 15, 351, 17),
    (150, 149, 2, None, None),
    (156, 155, 2, None, None),
    (158, 157, 2, None, None),
)
# These two backends serve ordinary plans. Only their old fixed-plan aliases are retired.
ALIAS_ONLY = ((349, 336, 15, 323), (350, 337, 16, 324))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def cleanup(db):
    db.row_factory = sqlite3.Row
    expected = {}
    pools = {}
    retired_sources = set()
    for source, backend, machine, alias, pool in RETIRED:
        retired_sources.add(source)
        expected[source] = (backend, None, None)
        expected[backend] = (0, machine, None)
        if alias:
            expected[alias] = (backend, None, pool)
            pools[pool] = (backend, source)
    for alias, backend, pool, source in ALIAS_ONLY:
        expected[alias] = (backend, None, pool)
        pools[pool] = (backend, source)

    def nodes():
        return {row['id']: dict(row) for row in db.execute('SELECT * FROM v2_server')}

    with db:
        db.execute('BEGIN IMMEDIATE')
        before = nodes()
        present = expected.keys() & before.keys()
        if not present:
            return {'deleted': [], 'remaining': len(before)}
        require(present == expected.keys(), 'Retirement inventory changed')
        kept = {i: row for i, row in before.items() if i not in expected}
        for i, row in before.items():
            if i in kept:
                require(row['parent_id'] not in expected and row['dedicated_exit_id'] not in pools,
                        f'Retained node {i} uses retired resources')
                continue
            identity = (row['parent_id'] or 0, row['machine_id'], row['dedicated_exit_id'])
            require(identity == expected[i] and row['type'] == 'vless' and
                    row['show'] == row['enabled'] == 0 and json.loads(row['group_ids']) == [],
                    f'Node {i} identity, visibility or authorization changed')

        for probe in db.execute('SELECT server_ids, expected_exits FROM v2_node_probe'):
            references = set(map(int, json.loads(probe['server_ids'])))
            references.update(map(int, json.loads(probe['expected_exits'] or '{}') or {}))
            require(references.isdisjoint(expected), 'A probe uses a retired node')
        for entry in db.execute('SELECT id, server_tunnels FROM v2_node_probe_ingress').fetchall():
            tunnels = json.loads(entry['server_tunnels'])
            overlap = set(map(int, tunnels)) & expected.keys()
            if overlap:
                require(overlap <= retired_sources, 'Unexpected ingress mapping')
                kept_tunnels = {k: v for k, v in tunnels.items() if int(k) not in overlap}
                require(kept_tunnels, 'Ingress would lose its entire scope')
                db.execute('UPDATE v2_node_probe_ingress SET server_tunnels = ? WHERE id = ?',
                           (json.dumps(kept_tunnels), entry['id']))

        occupied = {r[0] for r in db.execute('SELECT DISTINCT exit_id FROM v2_dedicated_assignment')}
        require(occupied.isdisjoint(pools), 'Retired pool has an assignment or reservation')
        exits = {r['id']: r for r in db.execute('SELECT * FROM v2_dedicated_exit')}
        require(pools.keys() <= exits.keys(), 'Retired pool inventory changed')
        for i, row in exits.items():
            refs = (row['shared_server_id'], row['probe_server_id'])
            if i not in pools:
                require(set(refs).isdisjoint(expected), f'Unexpected pool {i} references a retired node')
                continue
            require(refs == pools[i] and row['plan_id'] == 5 and not row['enabled'],
                    f'Pool {i} has changed')
            if row['shared_server_id'] in expected:
                db.execute('UPDATE v2_dedicated_exit SET shared_server_id=NULL, probe_server_id=NULL, '
                           'probe_id=NULL WHERE id=?', (i,))

        db.executemany('DELETE FROM v2_server WHERE id = ?', [(i,) for i in expected])
        require(nodes() == kept, 'Retained node configuration changed')
        return {'before': len(before), 'deleted': sorted(expected), 'remaining': len(kept)}


if __name__ == '__main__':
    with sqlite3.connect(DATABASE.resolve(strict=True).as_uri() + '?mode=rw', uri=True, timeout=30) as connection:
        connection.execute('PRAGMA foreign_keys = ON')
        print(json.dumps(cleanup(connection)))

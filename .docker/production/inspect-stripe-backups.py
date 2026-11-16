"""Read-only payment backup inventory; credentials never leave the origin host."""
import json
import re
import sqlite3
import urllib.request
from pathlib import Path

roots = [Path('/root/Xboard/backups'), Path('/root/xboard-backups'), Path('/root/Xboard/.docker/.data')]
results, seen = [], set()
scanned = 0
for root in roots:
    if not root.is_dir():
        continue
    for path in sorted(root.rglob('*'), key=lambda p: (not bool(re.search(r'stripe|payment', str(p), re.I)), str(p))):
        if path.is_symlink() or not path.is_file() or len(path.relative_to(root).parts) > 5:
            continue
        if not re.search(r'stripe|payment|sqlite', str(path), re.I):
            continue
        if path.name.endswith(('-shm', '-wal')) or path.stat().st_size > 100 * 1024 * 1024:
            continue
        item = {'path': str(path), 'accounts': []}
        candidates = []
        try:
            if 'sqlite' in path.name:
                db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
                try:
                    candidates = [str(r[0]) for r in db.execute("SELECT config FROM v2_payment WHERE payment = 'StripeCheckout'")]
                finally:
                    db.close()
            elif path.suffix == '.json' and path.stat().st_size < 2 * 1024 * 1024:
                candidates = [path.read_text()]
            else:
                continue
            for raw in candidates:
                for key in set(re.findall(r'\b[sr]k_live_[a-zA-Z0-9]+', raw)):
                    if key in seen:
                        continue
                    seen.add(key)
                    if len(seen) > 10:
                        raise SystemExit('Too many distinct payment keys; narrow inspection')
                    req = urllib.request.Request('https://api.stripe.com/v1/account', headers={'Authorization': 'Bearer ' + key})
                    try:
                        with urllib.request.urlopen(req, timeout=15) as r:
                            account = json.load(r).get('id')
                        item['accounts'].append(account)
                    except Exception:
                        item['account_lookup_failed'] = True
        except (ValueError, sqlite3.Error, OSError):
            item['unreadable'] = True
        scanned += 1
        if item['accounts'] or item.get('account_lookup_failed'):
            results.append(item)
        if scanned >= 500:
            raise SystemExit('Inspection limit reached; narrow inspection')
print(json.dumps({'read_only': True, 'files_scanned': scanned, 'backup_inventory': results}, ensure_ascii=False))

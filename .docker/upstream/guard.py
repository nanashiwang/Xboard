#!/usr/bin/env python3
"""Withdraw only approved extension routes when their upstream is no longer usable.

Private state and URL live outside Git. This guard never trusts new credentials,
changes package membership, or re-enables a withdrawn route without acceptance.
"""
import hashlib
import json
import os
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path('/root/Xboard/backups/upstream-20261022')


def fingerprint(node):
    return hashlib.sha256(json.dumps(node, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode()).hexdigest()


def evaluate(approved, proxies, usage, now):
    names = {}
    for node in proxies:
        names.setdefault(node.get('name'), []).append(node)
    reason = None
    if usage.get('expire', 0) <= now + 300:
        reason = 'expired_or_near_expiry'
    elif usage.get('total', 0) <= usage.get('upload', 0) + usage.get('download', 0):
        reason = 'quota_exhausted'
    disabled = []
    for row in approved:
        matches = names.get(row['source_name'], [])
        why = reason
        if not why and len(matches) != 1:
            why = 'missing_or_ambiguous_source'
        if not why and fingerprint(matches[0]) != row['source_sha256']:
            why = 'source_changed_requires_acceptance'
        if why:
            disabled.append({'key': row['key'], 'backend_id': row['backend_id'],
                             'public_id': row['public_id'], 'reason': why})
    return disabled


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def apply(withdraw, root=ROOT):
    request = root / 'guard.request.json'
    request.write_text(json.dumps(withdraw))
    request.chmod(0o600)
    container = subprocess.check_output(['docker', 'compose', 'ps', '-q', 'xboard'],
                                        cwd='/root/Xboard', text=True).strip()
    if not container:
        raise RuntimeError('application_not_running')
    target = '/www/storage/app/backups/upstream-20261022/guard.request.json'
    subprocess.run(['docker', 'cp', str(request), container + ':' + target], check=True,
                   capture_output=True, timeout=30)
    script = (root / 'guard-apply.php').read_text()
    result = subprocess.run(['docker', 'compose', 'exec', '-T', 'xboard', 'php'],
                            cwd='/root/Xboard', input=script, text=True,
                            capture_output=True, timeout=60)
    answer = json.loads(result.stdout)
    if result.returncode or 'error' in answer:
        raise RuntimeError('withdrawal_failed')
    return answer


def main():
    import yaml
    os.umask(0o077)
    approved = json.loads((ROOT / 'approved.private').read_text())
    previous = json.loads((ROOT / 'guard-state.json').read_text())
    now = int(time.time())
    try:
        url = (ROOT / 'source-url.secret').read_text().strip()
        if not url.startswith('https://'):
            raise ValueError('https_required')
        opener = urllib.request.build_opener(NoRedirect, urllib.request.ProxyHandler({}))
        req = urllib.request.Request(url, headers={'User-Agent': 'ClashMeta/1.19.32'})
        with opener.open(req, timeout=25) as response:
            raw = response.read(5 * 1024 * 1024 + 1)
            header = response.headers.get('subscription-userinfo', '')
        if len(raw) > 5 * 1024 * 1024:
            raise ValueError('response_too_large')
        data = yaml.safe_load(raw)
        if not isinstance(data, dict) or not isinstance(data.get('proxies'), list):
            raise ValueError('invalid_subscription')
        usage = {}
        for item in header.split(';'):
            key, _, value = item.strip().partition('=')
            if value.isdigit():
                usage[key] = int(value)
        if not all(k in usage for k in ('expire', 'total', 'upload', 'download')):
            raise ValueError('missing_quota_metadata')
        withdraw = evaluate(approved, data['proxies'], usage, now)
        state = {'checked_at': now, 'last_success_at': now, 'usage': usage,
                 'withdraw': withdraw, 'fetch_ok': True}
    except Exception as error:
        # Do not print URLs, headers, authentication, or exception messages.
        state = dict(previous, checked_at=now, fetch_ok=False, error_type=type(error).__name__)
        stale = now - previous.get('last_success_at', 0) > 86400
        expiring = previous.get('usage', {}).get('expire', 0) <= now + 300
        withdraw = [dict(key=r['key'], backend_id=r['backend_id'], public_id=r['public_id'],
                         reason='metadata_stale' if stale else 'known_expiry')
                    for r in approved] if stale or expiring else []
        state['withdraw'] = withdraw
    if withdraw:
        state['apply'] = apply(withdraw)
    temporary = ROOT / 'guard-state.next'
    temporary.write_text(json.dumps(state, indent=2))
    temporary.replace(ROOT / 'guard-state.json')
    print(json.dumps({'fetch_ok': state['fetch_ok'], 'withdraw_count': len(withdraw),
                      'checked_at': now}))


if __name__ == '__main__':
    main()

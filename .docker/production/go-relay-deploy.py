#!/usr/bin/env python3
"""Install the reviewed Go relay as a separate vhost on the existing shared host."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

DOMAIN = 'capybarago.uk'
SOURCE = Path('/etc/nginx/sites-enabled/taige.us')
SOURCE_SHA = '9cfef765dd98c7394da9908879c0ed2e7aafac635d358ff8b1069180317b30e4'
TARGET = Path('/etc/nginx/sites-enabled/capybarago.uk')
BACKUP = Path('/root/xboard-website-relay-go-20261102')
CANDIDATE = Path(__file__).with_name('go-relay.conf')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def run(*args):
    return subprocess.check_output(args, text=True, timeout=30).strip()


def neighbors():
    return {str(p): digest(p.read_bytes()) for p in TARGET.parent.iterdir() if p.is_file() and p != TARGET}


def candidate():
    if digest(SOURCE.read_bytes()) != SOURCE_SHA:
        raise RuntimeError('Existing relay template drifted')
    expected = SOURCE.read_text().replace('taige.us', DOMAIN).replace('xboard_website', 'capybara_go_relay').replace('xboard-website', 'capybara-go-relay').replace('@xboard_origin_acme', '@capybara_go_origin_acme').encode()
    if CANDIDATE.read_bytes() != expected:
        raise RuntimeError('Relay candidate differs from reviewed derivation')
    return expected


def activate(content):
    before = TARGET.read_bytes() if TARGET.exists() else None
    if TARGET.is_symlink() or (before is not None and before != content):
        raise RuntimeError('Refusing to replace another Go vhost')
    fd, filename = tempfile.mkstemp(prefix='capybara-go-', dir=str(TARGET.parent.parent))
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(content)
        os.chmod(filename, 0o644)
        os.replace(filename, TARGET)
        try:
            run('nginx', '-t')
            run('systemctl', 'reload', 'nginx')
        except Exception:
            if before is None:
                TARGET.unlink()
            else:
                TARGET.write_bytes(before)
            run('nginx', '-t')
            run('systemctl', 'reload', 'nginx')
            raise
    finally:
        Path(filename).unlink(missing_ok=True)


def verify():
    results = {}
    for path in ['/', '/api/v1/guest/comm/config', '/clients', '/desktop/login', '/downloads/SHA256SUMS.txt']:
        for attempt in range(4):
            try:
                body = run('curl', '--noproxy', '*', '--resolve', DOMAIN+':443:155.103.118.155', '-fsS', '--connect-timeout', '5', '--max-time', '20', 'https://'+DOMAIN+path)
                break
            except subprocess.CalledProcessError as error:
                if error.returncode not in (7, 52, 56, 60) or attempt == 3:
                    raise
                time.sleep(0.5)
        if path == '/':
            assert '点击进入官网' in body
        elif path.startswith('/api/'):
            assert json.loads(body)['data']['app_url'] == 'https://'+DOMAIN
        else:
            assert '点击进入官网' not in body
        results[path] = 'ok'
    return results


def main(operation):
    wanted = candidate()
    if operation == 'prepare':
        run('nginx', '-t')
        assert not TARGET.exists(), 'Go relay already exists'
        BACKUP.mkdir(mode=0o700, parents=True, exist_ok=True)
        state = {'neighbors': neighbors(), 'candidate_sha256': digest(wanted)}
        saved = BACKUP/'state.json'
        if saved.exists():
            assert json.loads(saved.read_text()) == state, 'Prepared state drifted'
        else:
            saved.write_text(json.dumps(state, indent=2));saved.chmod(0o600)
            (BACKUP/'candidate.conf').write_bytes(wanted)
        return {'prepared': True, 'existing_vhost_count': len(state['neighbors']), 'candidate_sha256': digest(wanted)}
    state = json.loads((BACKUP/'state.json').read_text())
    assert neighbors() == state['neighbors'], 'Shared vhosts changed'
    assert digest(wanted) == state['candidate_sha256'] and (BACKUP/'candidate.conf').read_bytes() == wanted, 'Candidate/backup drifted'
    if operation == 'activate':
        assert Path('/etc/letsencrypt/live/'+DOMAIN+'/fullchain.pem').is_file(), 'Certificate missing'
        activate(wanted)
    if operation in ('activate', 'verify'):
        assert TARGET.read_bytes() == wanted
        return {'checks': verify(), 'shared_vhosts_unchanged': neighbors()==state['neighbors'], 'certificate': run('openssl', 'x509', '-in', '/etc/letsencrypt/live/'+DOMAIN+'/fullchain.pem', '-noout', '-issuer', '-dates', '-ext', 'subjectAltName')}
    if operation == 'rollback':
        assert not TARGET.is_symlink() and TARGET.read_bytes() == wanted, 'Go vhost drifted'
        TARGET.unlink()
        try:
            run('nginx','-t');run('systemctl','reload','nginx')
        except Exception:
            activate(wanted)
            raise
        return {'removed_owned_vhost':True,'shared_vhosts_unchanged':neighbors()==state['neighbors']}
    raise ValueError('Unsupported operation')


if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('operation',choices=['prepare','activate','verify','rollback'])
    print(json.dumps(main(p.parse_args().operation),ensure_ascii=False,indent=2))

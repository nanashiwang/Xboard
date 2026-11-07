"""Inspect or atomically replace an existing node binary; never change credentials/config."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

EXPECTED_NEW = 'f002b9f882cc282911e6113c50d8f36a83cf77e2f558bd3104321a4cd104f6eb'
TARGETS = {
    'xboard-node': ('/usr/local/bin/xboard-node', '/etc/xboard-node/config.yml'),
    'xboard-extension': ('/usr/local/bin/xboard-extension-node', '/etc/xboard-extension/config.yml'),
}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def command(*args):
    return subprocess.check_output(args, text=True).strip()


def state(unit):
    binary, config = TARGETS[unit]
    pid = int(command('systemctl', 'show', unit, '-p', 'MainPID', '--value'))
    return {'unit': unit, 'active': command('systemctl', 'show', unit, '-p', 'ActiveState', '--value'),
            'pid': pid, 'binary_sha256': digest(binary), 'config_sha256': digest(config),
            'running_sha256': digest(f'/proc/{pid}/exe') if pid else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('unit', choices=TARGETS)
    parser.add_argument('--binary', type=Path)
    parser.add_argument('--expected-old-sha256')
    args = parser.parse_args()
    before = state(args.unit)
    if not args.binary:
        print(json.dumps(before))
        return
    if os.geteuid() != 0:
        raise SystemExit('Root required for installation')
    if before['active'] != 'active' or before['running_sha256'] != before['binary_sha256']:
        raise SystemExit('Existing service/file mismatch: inspect before deploying')
    if args.expected_old_sha256 != before['binary_sha256']:
        raise SystemExit('Existing binary differs from inspected SHA256')
    if digest(args.binary) != EXPECTED_NEW:
        raise SystemExit('New binary SHA256 mismatch')
    if before['binary_sha256'] == EXPECTED_NEW:
        print(json.dumps({'already_installed': True, **before}))
        return
    binary, config = map(Path, TARGETS[args.unit])
    backup = Path('/root/xboard-metering-backups') / f'{args.unit}-{time.time_ns()}'
    backup.mkdir(parents=True, mode=0o700)
    os.chmod(backup.parent, 0o700)
    shutil.copy2(binary, backup / 'node.before')
    shutil.copy2(config, backup / 'config.before')
    (backup / 'unit.before').write_text(command('systemctl', 'cat', args.unit))
    (backup / 'before.json').write_text(json.dumps(before))
    candidate = binary.with_name(binary.name + '.metering-next')
    shutil.copyfile(args.binary, candidate)
    os.chmod(candidate, binary.stat().st_mode & 0o777)
    os.chown(candidate, binary.stat().st_uid, binary.stat().st_gid)
    if digest(candidate) != EXPECTED_NEW or digest(config) != before['config_sha256']:
        raise SystemExit('Candidate/config changed during preparation')
    os.replace(candidate, binary)
    try:
        subprocess.run(['systemctl', 'restart', args.unit], check=True, timeout=90)
        time.sleep(5)
        after = state(args.unit)
        if after['active'] != 'active' or after['running_sha256'] != EXPECTED_NEW:
            raise RuntimeError('Restart did not run expected binary')
        if after['config_sha256'] != before['config_sha256']:
            raise RuntimeError('Configuration changed during restart')
    except Exception:
        shutil.copy2(backup / 'node.before', candidate)
        os.replace(candidate, binary)
        subprocess.run(['systemctl', 'restart', args.unit], check=True, timeout=90)
        print(json.dumps({'rolled_back': True, 'backup': str(backup), 'state': state(args.unit)}))
        raise
    (backup / 'after.json').write_text(json.dumps(after))
    print(json.dumps({'installed': True, 'backup': str(backup), 'state': after,
                      'acceptance': 'process only; proxy TCP/UDP and panel reports still require verification'}))


if __name__ == '__main__':
    main()

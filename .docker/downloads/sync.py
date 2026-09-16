#!/usr/bin/env python3
"""下载固定版本的官方客户端，校验 SHA-256 后发布到静态目录。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile


def checksum(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    manifest = json.loads(Path(__file__).with_name('manifest.json').read_text())
    args.directory.mkdir(parents=True, exist_ok=True)
    for asset in manifest:
        target = args.directory / asset['name']
        if target.exists() and target.stat().st_size == asset['size'] and checksum(target) == asset['sha256']:
            print('已校验：' + target.name, flush=True)
            continue
        fd, temporary = tempfile.mkstemp(prefix='.' + target.name, dir=args.directory)
        os.close(fd)
        temporary = Path(temporary)
        try:
            subprocess.run(['curl', '--fail', '--location', '--silent', '--show-error',
                            '--retry', '3', '--connect-timeout', '20', '--max-time', '900',
                            '--proto', '=https', '--proto-redir', '=https',
                            '--output', str(temporary), asset['url']], check=True)
            if temporary.stat().st_size != asset['size'] or checksum(temporary) != asset['sha256']:
                raise RuntimeError('文件大小或 SHA-256 不匹配：' + target.name)
            temporary.chmod(0o644)
            temporary.replace(target)
            print('下载并校验：' + target.name, flush=True)
        finally:
            temporary.unlink(missing_ok=True)
    sums = ''.join(a['sha256'] + '  ' + a['name'] + '\n' for a in manifest)
    fd, temporary = tempfile.mkstemp(prefix='.SHA256SUMS', dir=args.directory)
    with os.fdopen(fd, 'w') as stream:
        stream.write(sums)
    os.chmod(temporary, 0o644)
    os.replace(temporary, args.directory / 'SHA256SUMS.txt')


if __name__ == '__main__':
    main()

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


def validate_update_index(path, manifest, directory):
    """Publish the pointer only after every referenced, versioned asset is verified."""
    feed = json.loads(path.read_text())
    targets = {
        'darwin-aarch64': ('aarch64-apple-darwin', '.app.tar.gz'),
        'darwin-x86_64': ('x86_64-apple-darwin', '.app.tar.gz'),
        'windows-x86_64': ('x86_64-pc-windows-msvc', '.exe'),
        'linux-x86_64': ('x86_64-unknown-linux-gnu', '.AppImage'),
    }
    if set(feed.get('platforms', {})) != set(targets):
        raise RuntimeError('更新索引必须包含全部四个构建目标')
    assets = {asset['name']: asset for asset in manifest}
    for platform, (target, extension) in targets.items():
        name = f"Capybara_{feed['version']}_{target}{extension}"
        entry = feed['platforms'][platform]
        if entry['url'] != 'https://taige.us/downloads/' + name:
            raise RuntimeError('更新索引地址与版本不匹配')
        for filename in [name, name + '.sig']:
            asset = assets.get(filename)
            local = directory / filename
            if not asset or not local.is_file() or local.stat().st_size != asset['size'] or checksum(local) != asset['sha256']:
                raise RuntimeError('更新索引引用未校验的文件：' + filename)
        if entry['signature'] != (directory / (name + '.sig')).read_text().strip():
            raise RuntimeError('更新索引签名与附件不匹配')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    manifest = json.loads(Path(__file__).with_name('manifest.json').read_text())
    indexes = [index for index, asset in enumerate(manifest) if asset['name'] == 'capybara-latest.json']
    if indexes and indexes != [len(manifest) - 1]:
        raise RuntimeError('更新索引必须放在下载清单最后，全部附件完成后才能发布')
    args.directory.mkdir(parents=True, exist_ok=True)
    for asset in manifest:
        target = args.directory / asset['name']
        if target.exists() and target.stat().st_size == asset['size'] and checksum(target) == asset['sha256']:
            if target.name == 'capybara-latest.json':
                validate_update_index(target, manifest, args.directory)
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
            if target.name == 'capybara-latest.json':
                validate_update_index(temporary, manifest, args.directory)
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

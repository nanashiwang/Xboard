#!/usr/bin/env python3
"""下载固定版本的官方客户端，校验 SHA-256 后发布到静态目录。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile


INDEX_ORIGINS = {
    "capybara-latest.json": "https://taige.us",
    "capybara-current.json": "https://capybarago.uk",
    "capybara-hub.json": "https://capybarahub.fyi",
}


def checksum(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def validate_update_index(path, manifest, directory, name="capybara-latest.json"):
    origin = INDEX_ORIGINS[name]
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
        if entry['url'] != origin + '/downloads/' + name:
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
    indexes = [i for i, asset in enumerate(manifest) if asset['name'] in INDEX_ORIGINS]
    if indexes and indexes != list(range(len(manifest) - len(indexes), len(manifest))):
        raise RuntimeError('更新索引必须放在下载清单最后，全部附件完成后才能发布')
    if len({a['name'] for a in manifest}) != len(manifest):
        raise RuntimeError('下载清单不能包含重名文件')
    args.directory.mkdir(parents=True, exist_ok=True)
    staged = []
    try:
        for asset in manifest:
            target = args.directory / asset['name']
            is_index = target.name in INDEX_ORIGINS
            if target.exists() and target.stat().st_size == asset['size'] and checksum(target) == asset['sha256']:
                if is_index:
                    validate_update_index(target, manifest, args.directory, target.name)
                print('已校验：' + target.name, flush=True)
                continue
            fd, temporary = tempfile.mkstemp(prefix='.' + target.name, dir=args.directory)
            os.close(fd)
            temporary = Path(temporary)
            staged.append((temporary, target))
            subprocess.run(['curl', '--fail', '--location', '--silent', '--show-error',
                            '--retry', '3', '--connect-timeout', '20', '--max-time', '900',
                            '--proto', '=https', '--proto-redir', '=https',
                            '--output', str(temporary), asset['url']], check=True)
            if temporary.stat().st_size != asset['size'] or checksum(temporary) != asset['sha256']:
                raise RuntimeError('文件大小或 SHA-256 不匹配：' + target.name)
            temporary.chmod(0o644)
            if is_index:
                validate_update_index(temporary, manifest, args.directory, target.name)
            else:
                temporary.replace(target)
                print('下载并校验：' + target.name, flush=True)
        # Both indexes must validate before either pointer changes. An interrupted
        # rename can leave different versions, but each still references complete assets.
        for temporary, target in staged:
            if target.name in INDEX_ORIGINS:
                temporary.replace(target)
                print('发布更新索引：' + target.name, flush=True)
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)
    sums = ''.join(a['sha256'] + '  ' + a['name'] + '\n' for a in manifest)
    fd, temporary = tempfile.mkstemp(prefix='.SHA256SUMS', dir=args.directory)
    with os.fdopen(fd, 'w') as stream:
        stream.write(sums)
    os.chmod(temporary, 0o644)
    os.replace(temporary, args.directory / 'SHA256SUMS.txt')


if __name__ == '__main__':
    main()

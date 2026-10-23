import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch


class DownloadSyncTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        source = Path(__file__).resolve().parents[2] / '.docker/downloads/sync.py'
        shutil.copy(source, self.root / 'sync.py')
        spec = importlib.util.spec_from_file_location('download_sync', self.root / 'sync.py')
        self.sync = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.sync)
        self.directory = self.root / 'public'
        self.directory.mkdir()
        self.feed_path = self.directory / 'capybara-latest.json'
        self.feed_path.write_bytes(b'old published index')
        self.payloads = {}
        self.manifest = []
        platforms = {}
        for platform, target, extension in [
            ('darwin-aarch64', 'aarch64-apple-darwin', '.app.tar.gz'),
            ('darwin-x86_64', 'x86_64-apple-darwin', '.app.tar.gz'),
            ('windows-x86_64', 'x86_64-pc-windows-msvc', '.exe'),
            ('linux-x86_64', 'x86_64-unknown-linux-gnu', '.AppImage'),
        ]:
            name = f'Capybara_0.1.0-alpha.3_{target}{extension}'
            self.add_asset(name, ('fixture ' + platform).encode())
            self.add_asset(name + '.sig', ('signature ' + platform).encode())
            platforms[platform] = {'url': 'https://taige.us/downloads/' + name, 'signature': 'signature ' + platform}
        self.add_asset('capybara-latest.json', json.dumps({'version': '0.1.0-alpha.3', 'platforms': platforms}).encode())

    def add_asset(self, name, data):
        url = 'https://example.invalid/' + name
        self.payloads[url] = data
        self.manifest.append({'name': name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'url': url})

    def run_sync(self):
        (self.root / 'manifest.json').write_text(json.dumps(self.manifest))
        def download(command, **kwargs):
            Path(command[command.index('--output') + 1]).write_bytes(self.payloads[command[-1]])
        with patch.object(sys, 'argv', ['sync.py', str(self.directory)]), patch.object(self.sync.subprocess, 'run', side_effect=download):
            self.sync.main()

    def test_index_published_only_after_all_assets_and_idempotent(self):
        self.run_sync()
        self.assertEqual(self.feed_path.read_bytes(), self.payloads[self.manifest[-1]['url']])
        self.run_sync()
        self.assertTrue((self.directory / 'SHA256SUMS.txt').is_file())

    def test_bad_package_keeps_previous_index(self):
        self.payloads[self.manifest[0]['url']] = b'corrupted'
        with self.assertRaises(RuntimeError):
            self.run_sync()
        self.assertEqual(self.feed_path.read_bytes(), b'old published index')

    def test_wrong_target_or_signature_keeps_previous_index(self):
        feed = json.loads(self.payloads[self.manifest[-1]['url']])
        feed['platforms']['windows-x86_64']['signature'] = 'wrong signature'
        self.manifest.pop()
        self.add_asset('capybara-latest.json', json.dumps(feed).encode())
        with self.assertRaises(RuntimeError):
            self.run_sync()
        self.assertEqual(self.feed_path.read_bytes(), b'old published index')

    def test_index_cannot_be_uploaded_before_packages(self):
        self.manifest.insert(0, self.manifest.pop())
        with self.assertRaises(RuntimeError):
            self.run_sync()
        self.assertEqual(self.feed_path.read_bytes(), b'old published index')


if __name__ == '__main__':
    unittest.main()

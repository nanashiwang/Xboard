"""Real loopback TLS checks: no production endpoint, account, or network required."""
import base64
import hashlib
import importlib.util
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch


spec = importlib.util.spec_from_file_location(
    'runtime_guard', Path(__file__).resolve().parents[2] / '.docker/upstream/guard.py')
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


class LocalPeer:
    """Accept one connection, recording SNI and any decrypted application bytes."""

    def __init__(self, certificate=None, key=None, mode='tls'):
        self.mode = mode
        self.sni = []
        self.application_data = None
        self.errors = []
        self.stop = threading.Event()
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.bind(('127.0.0.1', 0))
        self.port = self.listener.getsockname()[1]
        self.listener.listen(1)
        self.listener.settimeout(2)
        if mode == 'tls':
            self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            self.context.load_cert_chain(str(certificate), str(key))
            self.context.set_servername_callback(
                lambda connection, name, context: self.sni.append(name))
        self.thread = threading.Thread(target=self.serve, daemon=True)

    def serve(self):
        try:
            connection, _ = self.listener.accept()
            with connection:
                connection.settimeout(2)
                if self.mode == 'silent':
                    self.stop.wait(2)
                elif self.mode == 'plaintext':
                    connection.recv(4096)
                    connection.sendall(b'not a TLS record\r\n')
                else:
                    with self.context.wrap_socket(connection, server_side=True) as tls:
                        self.application_data = tls.recv(4096)
        except Exception as error:
            self.errors.append(type(error).__name__)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join(timeout=3)
        self.listener.close()
        if self.thread.is_alive():
            raise AssertionError('local TLS fixture did not stop')


class RuntimeIdentityIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.openssl = shutil.which('openssl')
        if not cls.openssl:
            raise unittest.SkipTest('loopback TLS regression requires openssl')
        cls.directory = tempfile.TemporaryDirectory(prefix='xboard-runtime-identity-')
        cls.addClassCleanup(cls.directory.cleanup)
        root = Path(cls.directory.name)
        cls.key = root / 'approved-key.pem'
        cls.other_key = root / 'unapproved-key.pem'
        cls.certificate = root / 'approved.pem'
        cls.renewed_certificate = root / 'renewed.pem'
        cls.other_certificate = root / 'unapproved.pem'
        for key in (cls.key, cls.other_key):
            cls.openssl_command('genpkey', '-algorithm', 'EC', '-pkeyopt',
                                'ec_paramgen_curve:P-256', '-out', str(key))
            key.chmod(0o600)
        for key, certificate, serial in (
                (cls.key, cls.certificate, '1'),
                (cls.key, cls.renewed_certificate, '2'),
                (cls.other_key, cls.other_certificate, '3')):
            cls.openssl_command('req', '-new', '-x509', '-key', str(key),
                                '-out', str(certificate), '-days', '1',
                                '-set_serial', serial, '-subj', '/CN=fixture.invalid')
        # Derive the expected digest independently from the private key, not
        # through the certificate-extraction code under test.
        spki = cls.openssl_command('pkey', '-in', str(cls.key), '-pubout', '-outform', 'DER')
        cls.pin = base64.b64encode(hashlib.sha256(spki).digest()).decode('ascii')

    @classmethod
    def openssl_command(cls, *arguments):
        return subprocess.run([cls.openssl, *arguments], check=True, capture_output=True,
                              timeout=10).stdout

    def mapping(self, port):
        return {'key': 'U04', 'ip': '127.0.0.1', 'port': port,
                'sni': 'approved-upstream.invalid', 'pin': self.pin}

    def assert_no_application_data(self, peer):
        self.assertEqual([], peer.errors)
        self.assertEqual(['approved-upstream.invalid'], peer.sni)
        self.assertEqual(b'', peer.application_data,
                         'identity probing must not send AnyTLS credentials or application traffic')

    def test_approved_pin_uses_fixed_address_and_real_sni_without_application_traffic(self):
        with LocalPeer(self.certificate, self.key) as peer:
            result = guard.probe_identity(self.mapping(peer.port), timeout=1)
        self.assertIsNone(result)
        self.assert_no_application_data(peer)

    def test_renewed_certificate_with_same_public_key_remains_approved(self):
        self.assertNotEqual(self.certificate.read_bytes(), self.renewed_certificate.read_bytes())
        with LocalPeer(self.renewed_certificate, self.key) as peer:
            result = guard.probe_identity(self.mapping(peer.port), timeout=1)
        self.assertIsNone(result, 'the approved identity is SPKI, not the whole certificate')
        self.assert_no_application_data(peer)

    def test_changed_runtime_key_is_rejected_without_accepting_or_sending_credentials(self):
        with LocalPeer(self.other_certificate, self.other_key) as peer:
            mapping = self.mapping(peer.port)
            original = dict(mapping)
            result = guard.probe_identity(mapping, timeout=1)
        self.assertEqual('runtime_public_key_mismatch', result)
        self.assertEqual(original, mapping, 'an observed key must never replace the approved pin')
        self.assert_no_application_data(peer)

    def test_tcp_refusal_is_not_reported_as_a_public_key_mismatch(self):
        # A bound-but-not-listening socket times out on macOS; release a fresh
        # ephemeral listener so both macOS and Linux return connection refused.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as unavailable:
            unavailable.bind(('127.0.0.1', 0))
            unavailable.listen(1)
            port = unavailable.getsockname()[1]
        result = guard.probe_identity(self.mapping(port), timeout=0.5)
        self.assertEqual('runtime_tcp_unreachable', result)

    def test_plaintext_peer_is_a_tls_failure(self):
        with LocalPeer(mode='plaintext') as peer:
            result = guard.probe_identity(self.mapping(peer.port), timeout=1)
        self.assertEqual('runtime_tls_failed', result)
        self.assertEqual([], peer.errors)

    def test_peer_that_never_completes_handshake_times_out(self):
        with LocalPeer(mode='silent') as peer:
            result = guard.probe_identity(self.mapping(peer.port), timeout=0.15)
        self.assertEqual('runtime_identity_timeout', result)
        self.assertEqual([], peer.errors)

    def test_missing_openssl_after_real_tls_collection_returns_only_safe_reason(self):
        secret = 'sensitive-endpoint.invalid/password/test-secret-pin'
        error = FileNotFoundError(secret)
        with LocalPeer(self.certificate, self.key) as peer:
            with patch.object(guard.subprocess, 'run', side_effect=error) as command:
                result = guard.probe_identity(self.mapping(peer.port), timeout=1)
        self.assertEqual('runtime_identity_tool_unavailable', result)
        self.assertNotIn(secret, result)
        command.assert_called_once()
        self.assertTrue(command.call_args.kwargs['input'])
        self.assert_no_application_data(peer)

    def test_openssl_parse_failure_after_real_tls_collection_returns_only_safe_reason(self):
        secret = b'sensitive-endpoint.invalid/password/test-secret-pin'
        error = subprocess.CalledProcessError(1, ['openssl', 'x509'], output=secret, stderr=secret)
        with LocalPeer(self.certificate, self.key) as peer:
            with patch.object(guard.subprocess, 'run', side_effect=error) as command:
                result = guard.probe_identity(self.mapping(peer.port), timeout=1)
        self.assertEqual('runtime_certificate_invalid', result)
        self.assertNotIn(secret.decode(), result)
        command.assert_called_once()
        self.assertTrue(command.call_args.kwargs['input'])
        self.assert_no_application_data(peer)

    def test_openssl_timeout_after_real_tls_collection_returns_only_safe_reason(self):
        secret = b'sensitive-endpoint.invalid/password/test-secret-pin'
        error = subprocess.TimeoutExpired(['openssl', 'x509'], timeout=1, output=secret, stderr=secret)
        with LocalPeer(self.certificate, self.key) as peer:
            with patch.object(guard.subprocess, 'run', side_effect=error) as command:
                result = guard.probe_identity(self.mapping(peer.port), timeout=1)
        self.assertEqual('runtime_identity_timeout', result)
        self.assertNotIn(secret.decode(), result)
        command.assert_called_once()
        self.assertTrue(command.call_args.kwargs['input'])
        self.assert_no_application_data(peer)


if __name__ == '__main__':
    unittest.main()

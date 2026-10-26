"""Real CA/SNI TLS tests on loopback; no source credentials or external traffic."""
import base64
import hashlib
import importlib.util
from pathlib import Path
import socket
import ssl
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('prepare_ca', Path(__file__).resolve().parents[2] / '.docker/upstream/prepare.py')
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


class Peer:
    def __init__(self, certificate, key, silent=False):
        self.listener = socket.socket()
        self.listener.bind(('127.0.0.1', 0))
        self.listener.listen(1)
        self.listener.settimeout(2)
        self.port = self.listener.getsockname()[1]
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.load_cert_chain(str(certificate), str(key))
        self.names, self.errors, self.data = [], [], None
        self.context.set_servername_callback(lambda sock, name, ctx: self.names.append(name))
        self.stop = threading.Event()
        self.silent = silent
        self.thread = threading.Thread(target=self.serve, daemon=True)

    def serve(self):
        try:
            connection, _ = self.listener.accept()
            with connection:
                connection.settimeout(2)
                if self.silent:
                    self.stop.wait(2)
                else:
                    with self.context.wrap_socket(connection, server_side=True) as tls:
                        self.data = tls.recv(4096)
        except Exception as error:
            self.errors.append(type(error).__name__)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop.set()
        self.thread.join(3)
        self.listener.close()
        if self.thread.is_alive():
            raise AssertionError('TLS fixture did not stop')


class CAIdentityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix='xboard-ca-fixture-')
        cls.addClassCleanup(cls.temporary.cleanup)
        root = Path(cls.temporary.name)
        cls.ca, cls.cert, cls.key = root/'ca.pem', root/'server.pem', root/'server.key'
        config = root/'ca.cnf'
        config.write_text('[req]\ndistinguished_name=dn\nx509_extensions=ca\n[dn]\n[ca]\nbasicConstraints=critical,CA:TRUE\nkeyUsage=critical,keyCertSign,cRLSign\nsubjectKeyIdentifier=hash\n')
        extension = root/'server.ext'
        extension.write_text('basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\nextendedKeyUsage=serverAuth\nsubjectAltName=DNS:fixture.invalid\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid\n')
        cls.openssl('req', '-new', '-x509', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:P-256', '-nodes',
                    '-keyout', str(root/'ca.key'), '-out', str(cls.ca), '-days', '1', '-subj', '/CN=Fixture CA', '-config', str(config))
        cls.openssl('req', '-new', '-newkey', 'ec', '-pkeyopt', 'ec_paramgen_curve:P-256', '-nodes',
                    '-keyout', str(cls.key), '-out', str(root/'request'), '-subj', '/CN=fixture.invalid')
        cls.openssl('x509', '-req', '-in', str(root/'request'), '-CA', str(cls.ca), '-CAkey', str(root/'ca.key'),
                    '-CAcreateserial', '-out', str(cls.cert), '-days', '1', '-extfile', str(extension))
        spki = cls.openssl('pkey', '-in', str(cls.key), '-pubout', '-outform', 'DER')
        cls.pin = base64.b64encode(hashlib.sha256(spki).digest()).decode()

    @classmethod
    def openssl(cls, *args):
        return subprocess.run(['openssl', *args], check=True, capture_output=True, timeout=10).stdout

    def trusted_context(self):
        context = ssl.create_default_context(cafile=str(self.ca))
        self.assertTrue(context.check_hostname)
        self.assertEqual(ssl.CERT_REQUIRED, context.verify_mode)
        return context

    def test_ca_validated_fixed_ip_and_original_sni_send_no_application_data(self):
        context = self.trusted_context()
        with Peer(self.cert, self.key) as peer, patch.object(prepare.ssl, 'create_default_context', return_value=context):
            result = prepare.observe_ca('127.0.0.1', peer.port, 'fixture.invalid', timeout=2)
        self.assertEqual(self.pin, result['pin'])
        self.assertTrue(result['ca_validated'])
        self.assertTrue(result['certificate_time_valid'])
        self.assertEqual(['fixture.invalid'], peer.names)
        self.assertEqual(b'', peer.data)
        self.assertEqual([], peer.errors)

    def test_ca_trust_does_not_allow_wrong_sni(self):
        context = self.trusted_context()
        with Peer(self.cert, self.key) as peer, patch.object(prepare.ssl, 'create_default_context', return_value=context):
            result = prepare.observe_ca('127.0.0.1', peer.port, 'wrong.fixture.invalid', timeout=2)
        self.assertEqual({'reason': 'ca_validation_failed'}, result)
        self.assertIsNone(peer.data)

    def test_system_ca_context_rejects_untrusted_issuer_without_collecting_pin(self):
        with Peer(self.cert, self.key) as peer:
            result = prepare.observe_ca('127.0.0.1', peer.port, 'fixture.invalid', timeout=2)
        self.assertEqual({'reason': 'ca_validation_failed'}, result)
        self.assertIsNone(peer.data)

    def test_ca_shared_deadline_and_tool_errors_are_redacted(self):
        with Peer(self.cert, self.key, silent=True) as peer:
            result = prepare.observe_ca('127.0.0.1', peer.port, 'fixture.invalid', timeout=0.15)
        self.assertEqual({'reason': 'identity_timeout'}, result)
        context = self.trusted_context()
        with Peer(self.cert, self.key) as peer, patch.object(prepare.ssl, 'create_default_context', return_value=context), \
                patch.object(prepare.subprocess, 'run', side_effect=subprocess.CalledProcessError(1, ['private'], stderr=b'private certificate')):
            result = prepare.observe_ca('127.0.0.1', peer.port, 'fixture.invalid', timeout=2)
        self.assertEqual({'reason': 'certificate_invalid'}, result)
        self.assertEqual(b'', peer.data)


if __name__ == '__main__':
    unittest.main()

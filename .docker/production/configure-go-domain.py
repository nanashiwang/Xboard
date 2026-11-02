#!/usr/bin/env python3
"""Add the owned Go vhost without editing the existing application/relay vhosts."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

DOMAIN = "capybarago.uk"
ORIGIN = "107.173.191.23"
SOURCE = Path("/etc/nginx/sites-enabled/taige.us.conf")
SOURCE_SHA = "4625d1ef7e981fa42365fdde775bcd37605c6256835a5f9e166b8d8118bd5029"
TARGET = Path("/etc/nginx/sites-enabled/capybarago.uk.conf")
BACKUP = Path("/root/xboard-backups/capybara-go-20261102")
WEBROOT = Path("/var/www/xboard-acme")
MARKER = "# Xboard managed capybarago.uk"


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def http_config():
    return f'''{MARKER}
server {{
    listen 80;
    listen [::]:80;
    server_name {DOMAIN};
    access_log off;
    location ^~ /.well-known/acme-challenge/ {{
        root {WEBROOT};
        default_type text/plain;
    }}
    location / {{ return 308 https://{DOMAIN}$request_uri; }}
}}
'''


def https_config(source):
    if digest(source) != SOURCE_SHA:
        raise RuntimeError("Source vhost changed; review before deriving a new vhost")
    text = source.decode()
    start = text.index("server {", text.index("server {") + 1)
    https = text[start:]
    if https.count("server_name taige.us;") != 1:
        raise RuntimeError("Unexpected source server shape")
    https = https.replace("taige.us", DOMAIN)
    # The application entry does not expose VPN node locations or trust the relay.
    https = https.replace("    set_real_ip_from 155.103.118.155;\n", "")
    https = https.replace("    include /root/Xboard/.docker/.data/qiyun-cdn-nginx.conf;\n", "")
    if "qiyun-cdn" in https or "155.103.118.155" in https:
        raise RuntimeError("Unexpected node/relay configuration")
    if "include /opt/xboard-downloads/nginx.conf;" not in https:
        raise RuntimeError("Missing independent file download route")
    https = https.replace("    server_name " + DOMAIN + ";", "    server_name " + DOMAIN + ";\n    access_log /var/log/nginx/capybara-go.access.log capybara_go_safe;\n    error_log /var/log/nginx/capybara-go.error.log crit;")
    return (http_config() + "\nlog_format capybara_go_safe '$time_iso8601 $remote_addr $request_method $status bytes=$body_bytes_sent total=$request_time';\n\n" + https).encode()


def activate_bytes(content):
    before = TARGET.read_bytes() if TARGET.exists() else None
    if before is not None and (TARGET.is_symlink() or not before.startswith(MARKER.encode())):
        raise RuntimeError("Refusing to replace an unmanaged Go vhost")
    # Candidate outside sites-enabled: only the atomic final file is included.
    descriptor, filename = tempfile.mkstemp(prefix="capybara-go-", dir=str(TARGET.parent.parent))
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(content)
        os.chmod(filename, 0o644)
        os.replace(filename, TARGET)
        try:
            run("nginx", "-t")
            run("systemctl", "reload", "nginx")
        except Exception:
            if before is None:
                TARGET.unlink()
            else:
                TARGET.write_bytes(before)
            run("nginx", "-t")
            run("systemctl", "reload", "nginx")
            raise
    finally:
        Path(filename).unlink(missing_ok=True)


def verify():
    result = {}
    for path in ["/", "/clients", "/desktop/login", "/api/v1/guest/comm/config", "/downloads/SHA256SUMS.txt"]:
        body = run("curl", "--noproxy", "*", "--resolve", DOMAIN + ":443:" + ORIGIN, "-fsS", "--max-time", "20", "https://" + DOMAIN + path)
        if path == "/":
            assert "点击进入官网" in body
        elif path.startswith("/api/"):
            assert isinstance(json.loads(body)["data"], dict)
        else:
            assert "点击进入官网" not in body
        result[path] = "ok"
    return result




def application_settings(expected=None, replacement=None):
    """Read/update only the two public origins through the application's cache API."""
    payload = json.dumps({"expected": expected, "replacement": replacement})
    php = r"""<?php
require '/www/vendor/autoload.php';
$app = require '/www/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
$change = json_decode(PAYLOAD, true, 512, JSON_THROW_ON_ERROR);
$read = static fn() => ['app_url' => admin_setting('app_url'), 'subscribe_url' => admin_setting('subscribe_url')];
if ($change['replacement'] !== null) {
    Illuminate\Support\Facades\DB::transaction(function () use ($change, $read) {
        if ($read() !== $change['expected']) throw new RuntimeException('Application origins drifted');
        admin_setting($change['replacement']);
    });
}
echo json_encode($read(), JSON_THROW_ON_ERROR);
""".replace('PAYLOAD', "'" + payload.replace('\\', '\\\\').replace("'", "\\'") + "'")
    completed = subprocess.run(["docker", "compose", "exec", "-T", "xboard", "php"], input=php, text=True, capture_output=True, check=True)
    return json.loads(completed.stdout)


def change_primary(operation):
    """Keep old services and callbacks; change only generated application/subscription links."""
    backup = BACKUP / "settings.before.json"
    current = application_settings()
    desired = {"app_url": "https://" + DOMAIN, "subscribe_url": "https://" + DOMAIN}
    if operation == "promote":
        verify()  # Never promote before strict TLS and real application readiness.
        old = {"app_url": "https://taige.us", "subscribe_url": "https://taige.us"}
        if current not in (old, desired):
            raise RuntimeError("Unexpected application origins; refusing to overwrite")
        if not backup.exists():
            if current != old:
                raise RuntimeError("No original settings backup")
            with backup.open('x') as stream:
                os.chmod(backup, 0o600)
                json.dump(current, stream)
        if json.loads(backup.read_text()) != old:
            raise RuntimeError("Original settings backup drifted")
        result = application_settings(current, desired)
    else:
        original = json.loads(backup.read_text())
        if current != desired or original != {"app_url": "https://taige.us", "subscribe_url": "https://taige.us"}:
            raise RuntimeError("Settings drifted; refusing rollback")
        result = application_settings(current, original)
    run("docker", "compose", "exec", "-T", "xboard", "php", "artisan", "octane:reload")
    return {"origins": result, "changed_keys": ["app_url", "subscribe_url"], "payment_callbacks_unchanged": True}


def main(operation):
    os.chdir("/root/Xboard")
    if operation == "inspect":
        return {"source_sha256": digest(SOURCE.read_bytes()), "target_exists": TARGET.exists(), "nginx": run("nginx", "-t"), "container": run("docker", "compose", "ps", "xboard")}
    BACKUP.mkdir(mode=0o700, parents=True, exist_ok=True)
    if operation in ("promote", "rollback-settings"):
        return change_primary(operation)
    if operation == "prepare":
        source = SOURCE.read_bytes()
        candidate = https_config(source)
        (BACKUP / "source.sha256").write_text(digest(source))
        (BACKUP / "candidate.conf").write_bytes(candidate)
        if TARGET.exists():
            assert TARGET.read_bytes() in (http_config().encode(), candidate), "Go vhost drifted"
        else:
            activate_bytes(http_config().encode())
        challenge = WEBROOT / ".well-known/acme-challenge/capybara-go-probe"
        challenge.parent.mkdir(parents=True, exist_ok=True)
        challenge.write_text("capybara-go-ready")
        return {"prepared": True, "candidate_sha256": digest(candidate), "source_unchanged": digest(SOURCE.read_bytes()) == SOURCE_SHA}
    if operation == "activate":
        assert TARGET.read_bytes() in (http_config().encode(), (BACKUP / "candidate.conf").read_bytes()), "Go vhost drifted"
        # Existing ACME account and agreement; no new account or ToS acceptance.
        run("certbot", "certonly", "--webroot", "-w", str(WEBROOT), "-d", DOMAIN, "--cert-name", DOMAIN, "--non-interactive", "--keep-until-expiring")
        activate_bytes((BACKUP / "candidate.conf").read_bytes())
        assert digest(SOURCE.read_bytes()) == SOURCE_SHA
        return {"activated": True, "certificate": run("openssl", "x509", "-in", "/etc/letsencrypt/live/" + DOMAIN + "/fullchain.pem", "-noout", "-dates", "-ext", "subjectAltName"), "checks": verify()}
    if operation == "verify":
        return {"checks": verify(), "renewal_timer": run("systemctl", "is-active", "certbot.timer"), "origins": application_settings(), "source_unchanged": digest(SOURCE.read_bytes()) == SOURCE_SHA, "certificate": run("openssl", "x509", "-in", "/etc/letsencrypt/live/" + DOMAIN + "/fullchain.pem", "-noout", "-issuer", "-dates", "-ext", "subjectAltName")}
    if operation == "rollback":
        assert TARGET.read_bytes() in (http_config().encode(), (BACKUP / "candidate.conf").read_bytes()), "Go vhost drifted"
        before = TARGET.read_bytes()
        TARGET.unlink()
        try:
            run("nginx", "-t")
            run("systemctl", "reload", "nginx")
        except Exception:
            activate_bytes(before)
            raise
        return {"removed_owned_vhost": True, "source_unchanged": digest(SOURCE.read_bytes()) == SOURCE_SHA}
    raise ValueError("Unsupported operation")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["inspect", "prepare", "activate", "verify", "promote", "rollback-settings", "rollback"])
    print(json.dumps(main(parser.parse_args().operation), ensure_ascii=False, indent=2))

#!/usr/bin/env python3
"""Add the owned Hub vhost without editing the existing application/relay vhosts."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

DOMAIN = "app.capybarahub.fyi"
ORIGIN = "107.173.191.23"
SOURCE = Path("/etc/nginx/sites-enabled/taige.us.conf")
SOURCE_SHA = "4625d1ef7e981fa42365fdde775bcd37605c6256835a5f9e166b8d8118bd5029"
TARGET = Path("/etc/nginx/sites-enabled/app.capybarahub.fyi.conf")
BACKUP = Path("/root/xboard-backups/capybara-hub-20261103")
WEBROOT = Path("/var/www/xboard-acme")
MARKER = "# Xboard managed app.capybarahub.fyi"


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
    https = https.replace("    server_name " + DOMAIN + ";", "    server_name " + DOMAIN + ";\n    access_log /var/log/nginx/capybara-hub.access.log capybara_hub_safe;\n    error_log /var/log/nginx/capybara-hub.error.log crit;")
    return (http_config() + "\nlog_format capybara_hub_safe '$time_iso8601 $remote_addr $request_method $status bytes=$body_bytes_sent total=$request_time';\n\n" + https).encode()


def activate_bytes(content):
    before = TARGET.read_bytes() if TARGET.exists() else None
    if before is not None and (TARGET.is_symlink() or not before.startswith(MARKER.encode())):
        raise RuntimeError("Refusing to replace an unmanaged Hub vhost")
    # Candidate outside sites-enabled: only the atomic final file is included.
    descriptor, filename = tempfile.mkstemp(prefix="capybara-hub-", dir=str(TARGET.parent.parent))
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
    for path in ["/", "/clients", "/desktop/login", "/api/v1/guest/comm/config", "/api/v1/client/health"]:
        body = run("curl", "--noproxy", "*", "--resolve", DOMAIN + ":443:" + ORIGIN, "-fsS", "--max-time", "20", "https://" + DOMAIN + path)
        if path == "/":
            assert "点击进入官网" in body
        elif path == "/api/v1/client/health":
            assert json.loads(body) == {"service": "capybara-account", "protocol": 1}
        elif path.startswith("/api/"):
            assert isinstance(json.loads(body)["data"], dict)
        else:
            assert "点击进入官网" not in body
        result[path] = "ok"
    return result




def main(operation):
    os.chdir("/root/Xboard")
    if operation == "inspect":
        return {"source_sha256": digest(SOURCE.read_bytes()), "target_exists": TARGET.exists(), "nginx": run("nginx", "-t"), "container": run("docker", "compose", "ps", "xboard")}
    BACKUP.mkdir(mode=0o700, parents=True, exist_ok=True)
    if operation == "prepare":
        source = SOURCE.read_bytes()
        candidate = https_config(source)
        (BACKUP / "source.sha256").write_text(digest(source))
        (BACKUP / "candidate.conf").write_bytes(candidate)
        if TARGET.exists():
            assert TARGET.read_bytes() in (http_config().encode(), candidate), "Hub vhost drifted"
        else:
            activate_bytes(http_config().encode())
        challenge = WEBROOT / ".well-known/acme-challenge/capybara-hub-probe"
        challenge.parent.mkdir(parents=True, exist_ok=True)
        challenge.write_text("capybara-hub-ready")
        return {"prepared": True, "candidate_sha256": digest(candidate), "source_unchanged": digest(SOURCE.read_bytes()) == SOURCE_SHA}
    if operation == "activate":
        assert TARGET.read_bytes() in (http_config().encode(), (BACKUP / "candidate.conf").read_bytes()), "Hub vhost drifted"
        # Existing ACME account and agreement; no new account or ToS acceptance.
        run("certbot", "certonly", "--webroot", "-w", str(WEBROOT), "-d", DOMAIN, "--cert-name", DOMAIN, "--non-interactive", "--keep-until-expiring")
        activate_bytes((BACKUP / "candidate.conf").read_bytes())
        assert digest(SOURCE.read_bytes()) == SOURCE_SHA
        return {"activated": True, "certificate": run("openssl", "x509", "-in", "/etc/letsencrypt/live/" + DOMAIN + "/fullchain.pem", "-noout", "-dates", "-ext", "subjectAltName"), "checks": verify()}
    if operation == "verify":
        return {"checks": verify(), "renewal_timer": run("systemctl", "is-active", "certbot.timer"), "source_unchanged": digest(SOURCE.read_bytes()) == SOURCE_SHA, "certificate": run("openssl", "x509", "-in", "/etc/letsencrypt/live/" + DOMAIN + "/fullchain.pem", "-noout", "-issuer", "-dates", "-ext", "subjectAltName")}
    if operation == "rollback":
        assert TARGET.read_bytes() in (http_config().encode(), (BACKUP / "candidate.conf").read_bytes()), "Hub vhost drifted"
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
    parser.add_argument("operation", choices=["inspect", "prepare", "activate", "verify", "rollback"])
    print(json.dumps(main(parser.parse_args().operation), ensure_ascii=False, indent=2))

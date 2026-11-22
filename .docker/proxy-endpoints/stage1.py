#!/usr/bin/env python3
"""Install the fixed residential WebSocket routes on a PX host or the stage-one ingress."""
import argparse
import grp
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

HOSTS = {"a": "216.36.108.173", "b": "192.204.56.29"}
ENTRY = "143.203.200.5"
PORTS = range(20001, 20011)
DIRECTORY = Path("/etc/xboard-px-transport")
USER = "xboard-px-transport"
GOST = Path("/usr/local/lib/xboard-proxy-endpoints/gost")
DIGEST = "a60f87707d679d154fad93d05313284baf3dea71fdb9ec18afecaac35db946dd"
SNIPPET = Path("/etc/nginx/snippets/xboard-px-stage1.conf")


def run(*args):
    return subprocess.run(args, check=True, text=True, capture_output=True).stdout


def write(path, data, mode=0o644):
    if path.exists() and path.read_bytes() == data:
        return False
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as out:
        out.write(data)
        os.fchmod(out.fileno(), mode)
    os.replace(out.name, path)
    return True


def exit_config(key):
    host = HOSTS[key]
    services = []
    for port in PORTS:
        services.append({
            "name": f"stage1-{port}", "addr": f"{host}:{port + 3000}",
            "admission": "stage1", "handler": {"type": "tcp"},
            "listener": {"type": "wss", "metadata": {"path": "/ws"}, "tls": {
                "certFile": str(DIRECTORY / "server.crt"), "keyFile": str(DIRECTORY / "server.key")}},
            "forwarder": {"nodes": [{"name": "paid-endpoint", "addr": f"{host}:{port}"}]},
        })
    return {"services": services, "admissions": [
        {"name": "stage1", "whitelist": True, "matchers": [ENTRY]}]}


def install_exit(key):
    host = HOSTS[key]
    if hashlib.sha256(GOST.read_bytes()).hexdigest() != DIGEST or not any(
        addr["local"] == host for nic in json.loads(run("ip", "-j", "-4", "addr"))
        for addr in nic.get("addr_info", [])
    ):
        raise ValueError("PX host or installed GOST binary mismatch")
    if subprocess.run(["id", "-u", USER], capture_output=True).returncode:
        run("useradd", "--system", "--user-group", "--no-create-home", "--shell", "/usr/sbin/nologin", USER)
    DIRECTORY.mkdir(exist_ok=True)
    gid = grp.getgrnam(USER).gr_gid
    os.chown(DIRECTORY, 0, gid)
    DIRECTORY.chmod(0o750)
    cert, private = DIRECTORY / "server.crt", DIRECTORY / "server.key"
    if cert.exists() != private.exists():
        raise RuntimeError("incomplete PX TLS identity")
    if not cert.exists():
        dns = f"px-{key}.internal"
        with tempfile.TemporaryDirectory(dir=DIRECTORY) as tmp:
            run("openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1095",
                "-keyout", tmp + "/key", "-out", tmp + "/cert", "-subj", "/CN=" + dns,
                "-addext", "subjectAltName=DNS:" + dns, "-addext", "extendedKeyUsage=serverAuth",
                "-addext", "basicConstraints=critical,CA:TRUE")
            os.replace(tmp + "/key", private)
            os.replace(tmp + "/cert", cert)
    os.chown(private, 0, gid)
    private.chmod(0o640)
    config = DIRECTORY / "transport.json"
    changed = write(config, json.dumps(exit_config(key), indent=2).encode())
    unit = f"""[Unit]
Description=Fixed WebSocket forwarding from VPN stage one to purchased PX ports
After=network-online.target
Wants=network-online.target

[Service]
User={USER}
Group={USER}
ExecStart={GOST} -C {config}
Restart=on-failure
RestartSec=2
NoNewPrivileges=yes
PrivateTmp=yes
ProtectHome=yes
ProtectSystem=strict
IPAddressDeny=any
IPAddressAllow={host}/32 {ENTRY}/32

[Install]
WantedBy=multi-user.target
"""
    unit_changed = write(Path(f"/etc/systemd/system/{USER}.service"), unit.encode())
    if shutil.which("ufw") and "Status: active" in run("ufw", "status"):
        run("ufw", "allow", "proto", "tcp", "from", ENTRY, "to", host, "port", "23001:23010")
    if unit_changed:
        run("systemctl", "daemon-reload")
    run("systemctl", "enable", USER)
    run("systemctl", "restart" if changed or unit_changed else "start", USER)
    for _ in range(30):
        listeners = {line.split()[3] for line in run("ss", "-H", "-lnt").splitlines()}
        if all(f"{host}:{port + 3000}" in listeners for port in PORTS):
            return
        time.sleep(0.2)
    raise RuntimeError("PX transport listeners failed to start")


def routes(hosts=None, trust="/etc/nginx/xboard-px"):
    blocks = []
    for key, host in (HOSTS if hosts is None else hosts).items():
        for port in PORTS:
            blocks.append(f"""location = /residential/v1/{key}/{port} {{
    if ($http_upgrade !~* "^websocket$") {{ return 404; }}
    proxy_pass https://{host}:{port + 3000}/ws;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection upgrade;
    proxy_set_header Host px-{key}.internal;
    proxy_pass_request_headers off;
    proxy_set_header Sec-WebSocket-Key $http_sec_websocket_key;
    proxy_set_header Sec-WebSocket-Version $http_sec_websocket_version;
    proxy_ssl_server_name on;
    proxy_ssl_name px-{key}.internal;
    proxy_ssl_verify on;
    proxy_ssl_trusted_certificate {trust}/{key}.crt;
    proxy_connect_timeout 8s;
    proxy_read_timeout 1h;
    proxy_send_timeout 1h;
    proxy_buffering off;
    access_log off;
}}
""")
    return "".join(blocks)


def install_entry(certs):
    vhost = Path("/etc/nginx/sites-available/node.lumavia.fyi.conf")
    old = vhost.read_bytes()
    anchor = b" include /etc/nginx/snippets/hk-xboard-routes.conf;"
    include = f" include {SNIPPET};".encode()
    if old.count(anchor) != 1 or old.count(include) > 1:
        raise ValueError("unexpected ingress configuration")
    trust = Path("/etc/nginx/xboard-px")
    trust.mkdir(exist_ok=True)
    files = {}
    for key in HOSTS:
        cert = certs / f"{key}.crt"
        run("openssl", "verify", "-verify_hostname", f"px-{key}.internal", "-CAfile", cert, cert)
        files[trust / cert.name] = cert.read_bytes()
    files[SNIPPET] = routes().encode()
    if include not in old:
        files[vhost] = old.replace(anchor, include + b"\n" + anchor)
    backup = {p: p.read_bytes() if p.exists() else None for p in files}
    try:
        changed = [write(path, data) for path, data in files.items()]
        run("nginx", "-t")
        if any(changed):
            run("systemctl", "reload", "nginx")
    except BaseException:
        for p, data in backup.items():
            if data is None:
                p.unlink(missing_ok=True)
            else:
                write(p, data)
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="role", required=True)
    subs.add_parser("exit").add_argument("key", choices=HOSTS)
    subs.add_parser("entry").add_argument("public_certs", type=Path)
    args = parser.parse_args()
    try:
        if args.role == "exit":
            install_exit(args.key)
        else:
            install_entry(args.public_certs)
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"{exc.cmd[0]}: {exc.stderr.strip()}") from None

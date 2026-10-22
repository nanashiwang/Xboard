#!/usr/bin/env python3
"""Guarded taige.us origin preparation and redacted relay verification.

Run over SSH with ``python3 - inspect < website-relay-origin.py``. This helper
never prints raw nginx configuration, private keys, environment files or logs.
"""

import argparse
import base64
import contextlib
import fcntl
import hashlib
import json
import os
import queue
import re
import secrets
import stat
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


DOMAIN = "taige.us"
RELAY = "155.103.118.155"
ORIGIN = "107.173.191.23"
CONFIG = Path("/etc/nginx/sites-enabled/taige.us.conf")
BACKUPS = Path("/root/xboard-backups/website-relay-origin")
BASELINE_SHA256 = "4c2274c91eb95672dad7d5a6016313597f91bf61845ae36c8bec839d136ab615"
DEFAULT_CHANGE_ID = "20261022-flawless-website"
# Official ranges must be reviewed before adding a new relay generation.
# https://www.cloudflare.com/ips-v4 and https://www.cloudflare.com/ips-v6
CF_NETWORKS = (
    "173.245.48.0/20", "103.21.244.0/22", "103.22.200.0/22", "103.31.4.0/22",
    "141.101.64.0/18", "108.162.192.0/18", "190.93.240.0/20", "188.114.96.0/20",
    "197.234.240.0/22", "198.41.128.0/17", "162.158.0.0/15", "104.16.0.0/13",
    "104.24.0.0/14", "172.64.0.0/13", "131.0.72.0/22", "2400:cb00::/32",
    "2606:4700::/32", "2803:f800::/32", "2405:b500::/32", "2405:8100::/32",
    "2a06:98c0::/29", "2c0f:f248::/32",
)
RENEWAL = Path("/etc/letsencrypt/renewal/taige.us.conf")
SAFE_HEADERS = {
    "host", "x-real-ip", "x-forwarded-for", "x-forwarded-host",
    "x-forwarded-proto", "x-forwarded-port", "upgrade", "connection",
    "accept-encoding", "cf-connecting-ip",
}
SAFE_DIRECTIVES = {
    "listen", "server_name", "include", "root", "alias", "index",
    "try_files", "return", "proxy_pass", "proxy_http_version",
    "proxy_ssl_server_name", "proxy_ssl_name", "proxy_ssl_verify",
    "proxy_ssl_trusted_certificate", "proxy_ssl_verify_depth",
    "proxy_connect_timeout", "proxy_read_timeout", "proxy_send_timeout",
    "proxy_buffering", "proxy_request_buffering", "proxy_cache",
    "proxy_cache_bypass", "proxy_no_cache", "proxy_redirect",
    "proxy_set_header", "proxy_pass_request_headers", "proxy_pass_request_body",
    "set_real_ip_from", "real_ip_header", "real_ip_recursive",
    "gzip", "gzip_types", "gzip_min_length", "gzip_vary", "gzip_proxied",
    "gzip_comp_level", "gzip_disable", "gzip_static", "gunzip",
    "ssl_certificate", "ssl_certificate_key", "ssl_protocols",
    "ssl_session_timeout", "ssl_session_cache", "http2", "sendfile",
    "client_max_body_size", "client_body_timeout", "keepalive_timeout",
    "allow", "deny", "default_type", "autoindex", "add_header",
}
SAFE_RESPONSE_HEADERS = {
    "cache-control", "content-disposition", "x-content-type-options",
    "strict-transport-security", "access-control-allow-origin",
}
GLOBAL_DIRECTIVES = {
    name for name in SAFE_DIRECTIVES
    if name.startswith(("gzip", "real_ip", "set_real_ip", "proxy_"))
} | {"gunzip", "include", "client_max_body_size"}


def run(command):
    """Keep command diagnostics private: they may embed config literals."""
    try:
        result = subprocess.run(command, capture_output=True, text=True,
                                timeout=30, check=False)
        return result.returncode, result.stdout, result.stderr
    except (OSError, subprocess.TimeoutExpired):
        return 127, "", ""


class OperationError(Exception):
    """Only fixed machine-readable messages from this class may be printed."""


def digest(value):
    return hashlib.sha256(value).hexdigest()


def require(condition, code):
    if not condition:
        raise OperationError(code)


def checked(command, code):
    status, output, _ = run(command)
    require(status == 0, code)
    return output


def current_config():
    require(CONFIG.is_file() and not CONFIG.is_symlink(), "origin_config_not_regular")
    return CONFIG.read_bytes()


def replace_exact(source, old, new):
    require(source.count(old) == 1, "origin_config_shape_changed")
    return source.replace(old, new, 1)


def build_candidate(before):
    require(digest(before) == BASELINE_SHA256, "origin_baseline_sha_mismatch")
    source = before.decode()
    nodes = parse(source)
    require(len(nodes) == 2 and len(list(matching_servers(nodes))) == 2,
            "unexpected_origin_server_blocks")
    require(all(node["name"] == "server" for node in nodes), "unexpected_origin_top_level")
    require("real_ip_header" not in source and "set_real_ip_from" not in source,
            "origin_real_ip_already_configured")
    trust = "    # Xboard website relay: trust only the relay and Cloudflare.\n"
    trust += "".join("    set_real_ip_from " + item + ";\n" for item in (RELAY,) + CF_NETWORKS)
    trust += "    real_ip_header CF-Connecting-IP;\n    real_ip_recursive off;\n\n"
    source = replace_exact(source, "    ssl_certificate /etc/letsencrypt/live/taige.us/fullchain.pem;",
                           trust + "    ssl_certificate /etc/letsencrypt/live/taige.us/fullchain.pem;")
    source = replace_exact(source, "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;",
                           "proxy_set_header X-Forwarded-For $remote_addr;")
    source = replace_exact(source, "        proxy_set_header X-Forwarded-Proto https;",
                           "        proxy_set_header X-Forwarded-Proto https;\n"
                           "        proxy_set_header X-Forwarded-Host taige.us;\n"
                           "        proxy_set_header X-Forwarded-Port 443;\n"
                           "        proxy_set_header CF-Connecting-IP $remote_addr;\n"
                           '        proxy_set_header Forwarded "";\n'
                           '        proxy_set_header True-Client-IP "";')
    updated = parse(source)
    require(updated[0] == nodes[0], "http_acme_block_changed")
    return source.encode()


def atomic_write(path, content, mode=0o600, uid=None, gid=None):
    descriptor, temporary = tempfile.mkstemp(prefix="." + path.name + ".", dir=str(path.parent))
    try:
        os.fchmod(descriptor, mode)
        if uid is not None:
            os.fchown(descriptor, uid, gid)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def change_dir(change_id):
    require(bool(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", change_id)), "invalid_change_id")
    return BACKUPS / change_id


def read_state(change_id):
    directory = change_dir(change_id)
    require(directory.is_dir() and not directory.is_symlink(), "backup_not_found")
    state = json.loads((directory / "state.json").read_text())
    require(state.get("origin_config") == str(CONFIG), "backup_target_mismatch")
    before = (directory / "before.conf").read_bytes()
    after = (directory / "after.conf").read_bytes()
    require(digest(before) == state["before_sha256"] == BASELINE_SHA256, "backup_before_hash_mismatch")
    require(digest(after) == state["after_sha256"], "backup_after_hash_mismatch")
    require(after == build_candidate(before), "backup_candidate_mismatch")
    return state, before, after


def prepare(change_id):
    before = current_config()
    after = build_candidate(before)
    checked(["nginx", "-t"], "existing_nginx_config_invalid")
    directory = change_dir(change_id)
    if directory.exists():
        state, saved, candidate = read_state(change_id)
        require(saved == before and candidate == after, "existing_backup_conflict")
        return {"operation": "prepare", "already_prepared": True, **state}
    BACKUPS.mkdir(mode=0o700, parents=True, exist_ok=True)
    directory.mkdir(mode=0o700)
    metadata = CONFIG.stat()
    state = {"origin_config": str(CONFIG), "before_sha256": digest(before), "after_sha256": digest(after),
             "mode": stat.S_IMODE(metadata.st_mode), "uid": metadata.st_uid, "gid": metadata.st_gid,
             "backup_directory": str(directory)}
    atomic_write(directory / "before.conf", before)
    atomic_write(directory / "after.conf", after)
    atomic_write(directory / "state.json", (json.dumps(state, indent=2) + "\n").encode())
    return {"operation": "prepare", "active_config_unchanged": current_config() == before, **state}


def install_config(content, state):
    atomic_write(CONFIG, content, state["mode"], state["uid"], state["gid"])


def activate_with_recovery(previous, desired, state):
    require(current_config() == previous, "active_config_conflict")
    checked(["nginx", "-t"], "existing_nginx_config_invalid")
    install_config(desired, state)
    try:
        checked(["nginx", "-t"], "candidate_nginx_config_invalid")
        checked(["systemctl", "reload", "nginx"], "candidate_nginx_reload_failed")
    except OperationError as failure:
        require(current_config() == desired, "failure_recovery_config_conflict")
        install_config(previous, state)
        checked(["nginx", "-t"], "recovery_nginx_config_invalid")
        checked(["systemctl", "reload", "nginx"], "recovery_nginx_reload_failed")
        raise OperationError(str(failure) + "_previous_config_restored")
    require(current_config() == desired, "post_reload_config_conflict")


def apply_change(change_id, rollback=False):
    state, before, after = read_state(change_id)
    old, new = (after, before) if rollback else (before, after)
    operation = "rollback" if rollback else "apply"
    if current_config() == new:
        checked(["nginx", "-t"], "existing_nginx_config_invalid")
        return {"operation": operation, "already_applied": True, "active_sha256": digest(new)}
    activate_with_recovery(old, new, state)
    return {"operation": operation, "active_sha256": digest(new), "nginx_reloaded": True}


@contextlib.contextmanager
def operation_lock():
    with open("/run/lock/xboard-website-relay-origin.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield


def laravel_assertions(samples):
    # Run the installed middleware against actual headers collected by the
    # temporary origin receiver. A Caddy-style private hop is appended, without
    # changing any running Caddy/Octane process or injecting business routes.
    encoded = base64.b64encode(json.dumps(samples).encode()).decode()
    php = """<?php
require '/www/vendor/autoload.php';
$app = require '/www/bootstrap/app.php';
$app->make(Illuminate\\Contracts\\Console\\Kernel::class)->bootstrap();
$samples = json_decode(base64_decode('%s'), true, 512, JSON_THROW_ON_ERROR);
$results = [];
foreach ($samples as $sample) {
    $headers = $sample['headers'];
    $request = Illuminate\\Http\\Request::create('https://taige.us/', 'GET', [], [], [], [
        'REMOTE_ADDR' => '127.0.0.1',
        'HTTP_HOST' => $headers['host'],
        'HTTP_X_FORWARDED_FOR' => $headers['x-forwarded-for'].', 172.17.0.1',
        'HTTP_X_FORWARDED_PROTO' => $headers['x-forwarded-proto'],
        'HTTP_X_FORWARDED_HOST' => $headers['x-forwarded-host'],
        'HTTP_X_FORWARDED_PORT' => $headers['x-forwarded-port'],
    ]);
    (new App\\Http\\Middleware\\TrustProxies)->handle($request, function ($request) use (&$results, $sample) {
        $results[$sample['name']] = ['client_ip_matches' => $request->ip() === $sample['expected'],
            'scheme_https' => $request->isSecure(), 'host_matches' => $request->getHost() === 'taige.us'];
        return new Illuminate\\Http\\Response('');
    });
}
echo json_encode($results, JSON_THROW_ON_ERROR);
""" % encoded
    result = subprocess.run(["docker", "compose", "exec", "-T", "xboard", "php"],
                            cwd="/root/Xboard", input=php, text=True, capture_output=True,
                            timeout=30, check=False)
    require(result.returncode == 0, "laravel_diagnostic_failed")
    data = json.loads(result.stdout)
    require(set(data) == {item["name"] for item in samples}, "laravel_diagnostic_shape_mismatch")
    require(all(value is True for checks in data.values() for value in checks.values()),
            "laravel_identity_assertion_failed")
    return data


def curl_probe(url, address, extra_headers=()):
    parsed = urlsplit(url)
    port = 443 if parsed.scheme == "https" else 80
    command = ["curl", "--silent", "--show-error", "--fail", "--noproxy", "*",
               "--connect-timeout", "10", "--max-time", "25", "--resolve",
               DOMAIN + ":" + str(port) + ":" + address, "--write-out", "\n%{http_code}", url]
    for header in extra_headers:
        command.extend(["-H", header])
    for attempt in range(4):
        status, output, _ = run(command)
        body, separator, http_status = output.rpartition("\n")
        if status == 0 and separator and http_status == "200":
            return body
        # A graceful reload may briefly serve the previous config. Retry only
        # missing routes or transient connection closure, never failed identity
        # assertions or upstream application/server errors.
        transient = (status == 22 and http_status == "404") or status in {7, 52, 56}
        if transient and attempt < 3:
            time.sleep(0.5)
            continue
        raise OperationError("verification_http_request_failed")


def verify(change_id):
    state, _, after = read_state(change_id)
    require(current_config() == after, "verification_requires_applied_config")
    nonce = secrets.token_hex(24)
    endpoint = "/__xboard_relay_verify_" + nonce
    received = queue.Queue()

    class Receiver(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path != endpoint or self.headers.get("X-Xboard-Diagnostic") != nonce:
                self.send_error(404)
                return
            headers = {name: self.headers.get(name, "") for name in (
                "host", "x-real-ip", "x-forwarded-for", "x-forwarded-host",
                "x-forwarded-proto", "x-forwarded-port", "cf-connecting-ip",
                "forwarded", "true-client-ip")}
            received.put(headers)
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"xboard-relay-verify")

        def log_message(self, *args):
            pass

    receiver = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    receiver.daemon_threads = True
    thread = threading.Thread(target=receiver.serve_forever, daemon=True)
    thread.start()
    port = receiver.server_address[1]
    source = after.decode()
    # Copy the live application location's identity assignments into the probe;
    # this keeps the verification coupled to the configuration under review.
    root_location = next(node for node in parse(source)[1]["children"]
                         if node["name"] == "location" and node["args"] == ["/"])
    forwarded = [node for node in root_location["children"] if node["name"] == "proxy_set_header"
                 and node["args"][0].lower() not in {"upgrade", "connection"}]
    diagnostic = "\n    location = " + endpoint + " {\n"
    diagnostic += "        allow 127.0.0.1;\n        allow " + ORIGIN + ";\n        allow " + RELAY + ";\n        deny all;\n"
    diagnostic += "        access_log off;\n        error_log /dev/null crit;\n"
    diagnostic += "        proxy_pass http://127.0.0.1:" + str(port) + ";\n"
    diagnostic += "".join("        proxy_set_header " + " ".join(node["args"]) + ";\n" for node in forwarded)
    diagnostic += "        proxy_set_header X-Xboard-Diagnostic " + nonce + ";\n    }\n"
    position = source.rfind("}")
    temporary = (source[:position] + diagnostic + source[position:]).encode()
    challenge = Path("/var/www/xboard-acme/.well-known/acme-challenge/xboard-relay-" + nonce)
    samples, changed = [], False
    try:
        activate_with_recovery(after, temporary, state)
        changed = True
        spoofed = ("X-Forwarded-For: 198.51.100.27", "CF-Connecting-IP: 203.0.113.38",
                   "X-Forwarded-Host: spoof.invalid", "X-Forwarded-Proto: http",
                   "X-Forwarded-Port: 80", "Forwarded: for=198.51.100.27", "True-Client-IP: 203.0.113.38")
        for name, address, expected in (("direct_origin_spoof", "127.0.0.1", "127.0.0.1"),
                                        ("relay_spoof", RELAY, ORIGIN)):
            require(curl_probe("https://" + DOMAIN + endpoint, address, spoofed) == "xboard-relay-verify",
                    "diagnostic_response_mismatch")
            headers = received.get(timeout=5)
            require(headers["x-forwarded-for"] == expected and headers["x-real-ip"] == expected,
                    "origin_identity_headers_incorrect")
            require(not headers["forwarded"] and not headers["true-client-ip"], "spoofed_identity_header_preserved")
            samples.append({"name": name, "expected": expected, "headers": headers})
        results = laravel_assertions(samples)
        require(challenge.parent.is_dir() and not challenge.exists(), "acme_probe_path_invalid")
        challenge.write_text("xboard-origin-acme-" + nonce)
        os.chmod(challenge, 0o644)
        require(curl_probe("http://" + DOMAIN + "/.well-known/acme-challenge/" + challenge.name, RELAY)
                == challenge.read_text(), "origin_acme_fallback_mismatch")
    finally:
        if challenge.exists():
            challenge.unlink()
        try:
            if changed:
                # Never restore a temporary diagnostic block on cleanup failure.
                require(current_config() == temporary, "diagnostic_cleanup_config_conflict")
                install_config(after, state)
                checked(["nginx", "-t"], "diagnostic_cleanup_nginx_config_invalid")
                checked(["systemctl", "reload", "nginx"], "diagnostic_cleanup_nginx_reload_failed")
        finally:
            receiver.shutdown()
            receiver.server_close()
            thread.join(timeout=5)
    return {"operation": "verify", "middleware_assertions": results, "origin_acme_fallback": True,
            "diagnostic_cleaned": current_config() == after and not challenge.exists() and not thread.is_alive(),
            "scope": "origin HTTP forwarding plus installed Laravel middleware; no business route or Octane reload"}


def tokenize(source):
    # Nginx variables with braced names are a single token, not config blocks.
    pattern = r'''\s+|\#[^\n]*|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[{};]|(?:\\.|\$\{[^}]+\}|[^\s{};#"'])+'''
    tokens = []
    end = 0
    for match in re.finditer(pattern, source):
        if match.start() != end:
            raise ValueError("Unsupported nginx syntax")
        end = match.end()
        token = match.group()
        if not token.isspace() and not token.startswith("#"):
            tokens.append(token)
    if end != len(source):
        raise ValueError("Incomplete nginx syntax")
    return tokens


def parse(source):
    root, stack, pending = [], [], []
    current = root
    for token in tokenize(source):
        if token == "{":
            if not pending:
                raise ValueError("Unnamed nginx block")
            node = {"name": pending[0], "args": pending[1:], "children": []}
            current.append(node)
            stack.append(current)
            current, pending = node["children"], []
        elif token == "}":
            if pending or not stack:
                raise ValueError("Unbalanced nginx block")
            current = stack.pop()
        elif token == ";":
            if pending:
                current.append({"name": pending[0], "args": pending[1:]})
                pending = []
        else:
            pending.append(token)
    if pending or stack:
        raise ValueError("Unterminated nginx directive")
    return root


def unquote(value):
    return value[1:-1] if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'" else value


def safe_args(name, args):
    args = [unquote(arg) for arg in args]
    if name in {"proxy_set_header", "add_header"}:
        headers = SAFE_HEADERS if name == "proxy_set_header" else SAFE_RESPONSE_HEADERS
        if not args or args[0].lower() not in headers:
            return ["<unlisted header omitted>"]
        if name == "proxy_set_header" and any(
            not re.fullmatch(r"(?:\$[a-zA-Z_][a-zA-Z0-9_]*|\$\{[a-zA-Z_][a-zA-Z0-9_]*\}|[,:. /])*", value)
            and value not in {"", "https", "http", "upgrade", "close", "keep-alive", "websocket", "443", "80", DOMAIN}
            for value in args[1:]
        ):
            return [args[0], "<literal header value omitted>"]
    if name == "proxy_pass" and args:
        parsed = urlsplit(args[0])
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            return ["<upstream contains credentials or query; omitted>"]
        # Route prefixes are needed for review; never expose opaque tokens.
        if parsed.path not in {"", "/", "/ws"}:
            args[0] = args[0][:-len(parsed.path)] + "/<path omitted>"
    if name == "return" and len(args) > 1:
        value = args[1]
        if not re.fullmatch(r"https?://(?:taige\.us|board\.taige\.us|\$host)(?:\$request_uri|/)?", value):
            args[1:] = ["<response value omitted>"]
    # Safe config may contain variables and certificate *paths*, never key data.
    if any(re.search(r"BEGIN .*PRIVATE KEY|(?:bearer|password|secret|token)\s*[=: ]", arg, re.I)
           for arg in args):
        return ["<sensitive value omitted>"]
    return args


def render_safe(nodes, prefix="", global_only=False):
    output = []
    for node in nodes:
        name, args = node["name"], node["args"]
        if "children" in node:
            if global_only and name == "server":
                continue
            # Do not print arbitrary map/if expression values or user paths.
            label = name
            if name == "location":
                allowed = {"/", "/ws", "/downloads/", "/.well-known/acme-challenge/", "^~", "=", "~", "~*", r"/\."}
                label += " " + " ".join(arg if unquote(arg) in allowed else "<pattern omitted>" for arg in args)
            children = render_safe(node["children"], prefix + "  ", global_only)
            if children:
                output.extend([prefix + label + " {"] + children + [prefix + "}"])
        elif name in (GLOBAL_DIRECTIVES if global_only else SAFE_DIRECTIVES):
            output.append(prefix + name + " " + " ".join(safe_args(name, args)) + ";")
    return output


def matching_servers(nodes):
    for node in nodes:
        children = node.get("children", [])
        if node["name"] == "server" and any(
            child["name"] == "server_name" and DOMAIN in map(unquote, child["args"])
            for child in children
        ):
            yield node
        else:
            yield from matching_servers(children)


def inspect_nginx():
    code, dump, _ = run(["nginx", "-T"])
    report = {"config_test_ok": code == 0, "exit_code": code,
              "target_servers": [], "related_configuration": []}
    sections = re.split(r"^# configuration file ([^\n]+):\n", dump, flags=re.M)
    for index in range(1, len(sections), 2):
        filename, source = sections[index:index + 2]
        identity = {"file": filename, "dump_sha256": hashlib.sha256(source.encode()).hexdigest()}
        path = Path(filename)
        if path.is_file():
            identity.update({"file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                             "resolved_file": str(path.resolve()), "is_symlink": path.is_symlink()})
        try:
            nodes = parse(source)
        except ValueError:
            report["related_configuration"].append({**identity, "parse_error": True})
            continue
        for server in matching_servers(nodes):
            report["target_servers"].append({**identity, "configuration": render_safe([server])})
        related = render_safe(nodes, global_only=True)
        if related:
            report["related_configuration"].append({**identity, "configuration": related})
    code_v, _, version = run(["nginx", "-V"])
    match = re.search(r"nginx/[\w.~-]+", version)
    report["version"] = match.group() if match else None
    report["http_realip_module"] = code_v == 0 and "--with-http_realip_module" in version
    return report


def inspect_certificate():
    certificate = Path("/etc/letsencrypt/live/taige.us/fullchain.pem")
    code, details, _ = run(["openssl", "x509", "-in", str(certificate), "-noout",
                            "-subject", "-issuer", "-dates", "-fingerprint", "-sha256"])
    report = {"certificate": str(certificate), "readable": code == 0,
              "public_details": details.splitlines() if code == 0 else []}
    report["renewal_file_exists"] = RENEWAL.is_file()
    if RENEWAL.is_file():
        allowed = {"version", "archive_dir", "cert", "chain", "fullchain", "authenticator",
                   "installer", "server", "webroot_path", "taige.us"}
        values = {}
        for line in RENEWAL.read_text().splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip() in allowed:
                values[key.strip()] = value.strip()
        report["renewal"] = values
    hook = Path("/etc/letsencrypt/renewal-hooks/deploy/xboard-nginx")
    report["deploy_hook_exists"] = hook.is_file()
    if hook.is_file():
        content = hook.read_text()
        report["deploy_hook"] = {
            "sha256": hashlib.sha256(content.encode()).hexdigest(),
            "checks_nginx": bool(re.search(r"^nginx -t\s*$", content, re.M)),
            "reloads_nginx": bool(re.search(r"^systemctl reload nginx\s*$", content, re.M)),
        }
    for verb in ("is-enabled", "is-active"):
        code, status, _ = run(["systemctl", verb, "certbot.timer"])
        value = status.strip()
        report["certbot_timer_" + verb[3:]] = value if value in {
            "enabled", "disabled", "static", "masked", "active", "inactive", "failed"
        } else "unavailable"
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["inspect", "prepare", "apply", "verify", "rollback"])
    parser.add_argument("--change-id", default=DEFAULT_CHANGE_ID)
    arguments = parser.parse_args()
    try:
        if arguments.operation == "inspect":
            report = {"operation": "inspect", "read_only": True, "domain": DOMAIN,
                      "nginx": inspect_nginx(), "certificate": inspect_certificate()}
        else:
            require(os.geteuid() == 0, "root_required")
            with operation_lock():
                if arguments.operation == "prepare":
                    report = prepare(arguments.change_id)
                elif arguments.operation == "verify":
                    report = verify(arguments.change_id)
                else:
                    report = apply_change(arguments.change_id, rollback=arguments.operation == "rollback")
        print(json.dumps(report, ensure_ascii=False, indent=2))
        if arguments.operation == "inspect":
            return 0 if report["nginx"]["config_test_ok"] and report["nginx"]["target_servers"] else 1
        return 0
    except Exception as error:
        # Error messages can contain source text; emit only the exception type.
        report = {"operation": arguments.operation, "error_type": type(error).__name__}
        if isinstance(error, OperationError):
            report["error_code"] = str(error)
        print(json.dumps(report), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

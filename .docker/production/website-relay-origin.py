#!/usr/bin/env python3
"""Read-only, redacted inspection of the taige.us origin before relay changes.

Run over SSH with ``python3 - inspect < website-relay-origin.py``. This helper
never prints raw nginx configuration, private keys, environment files or logs.
"""

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit


DOMAIN = "taige.us"
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
    parser.add_argument("operation", choices=["inspect"])
    parser.parse_args()
    try:
        report = {"operation": "inspect", "read_only": True, "domain": DOMAIN,
                  "nginx": inspect_nginx(), "certificate": inspect_certificate()}
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["nginx"]["config_test_ok"] and report["nginx"]["target_servers"] else 1
    except Exception as error:
        # Error messages can contain source text; emit only the exception type.
        print(json.dumps({"operation": "inspect", "error_type": type(error).__name__}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

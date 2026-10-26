#!/usr/bin/env python3
"""Read fixed local environment metadata only; never expose URLs or credentials."""
import hashlib
import grp
import ipaddress
import json
import os
import pwd
from pathlib import Path
import re
import stat
import subprocess
import sys
import urllib.parse

AGENT = Path('/etc/xboard-extension-probe/agent.json')
BINARY_PATHS = ('/usr/local/bin/sing-box', '/usr/bin/sing-box', '/opt/xboard-node-probe/sing-box',
                '/root/Xboard/backups/fleet-20261017/sing-box')
UNITS = ('xboard-upstream-guard.timer', 'xboard-upstream-guard.service')
PROPERTIES = ('ActiveState', 'SubState', 'Result', 'TimeoutStartUSec')
PROBE_UNIT = 'xboard-extension-probe.service'
PROBE_PROPERTIES = ('LoadState', 'User', 'Group', 'DynamicUser', 'ActiveState', 'SubState', 'Result')
ACCOUNT_NAME = re.compile(r'^(?:[A-Za-z_][A-Za-z0-9_.-]{0,31}|[0-9]{1,10})$')
FIELD_NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_]{0,31}$')
ACTIVE_VALUES = {'active', 'reloading', 'inactive', 'failed', 'activating', 'deactivating', 'maintenance', 'refreshing'}
SUB_VALUES = {'dead', 'waiting', 'running', 'elapsed', 'failed', 'exited', 'start', 'start-pre', 'start-post',
              'stop', 'stop-watchdog', 'stop-sigterm', 'stop-sigkill', 'stop-post', 'final-sigterm', 'final-sigkill',
              'auto-restart', 'auto-restart-queued', 'cleaning', 'condition', 'reload', 'reload-signal', 'reload-notify',
              'listening', 'plugged', 'mounted', 'mounting', 'unmounting', 'active', 'inactive'}
RESULT_VALUES = {'success', 'resources', 'timeout', 'exit-code', 'signal', 'core-dump', 'watchdog', 'start-limit-hit',
                 'protocol', 'oom-kill', 'exec-condition', 'assert', 'condition', 'dependency', 'cancelled', 'skipped'}
DURATION = re.compile(r'^(?:0|infinity|(?:[0-9]+(?:\.[0-9]+)?(?:us|ms|s|min|h|d|w|month|y)(?: )?)+)$')


def root_owned(info):
    return info.st_uid == 0


def parse_json(raw):
    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise ValueError()
            result[key] = item
        return result
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))


def panel_url_metadata(value):
    report = {'is_string': isinstance(value, str), 'parse_valid': False, 'scheme': 'unknown',
              'host_is_loopback': False, 'host_is_expected_public': False, 'path_is_root': False,
              'has_userinfo': False, 'has_query': False, 'has_fragment': False, 'port_class': 'invalid'}
    if not isinstance(value, str):
        return report
    try:
        parsed = urllib.parse.urlsplit(value)
        host = parsed.hostname
        report.update(scheme=parsed.scheme if parsed.scheme in ('http', 'https') else 'missing' if not parsed.scheme else 'other',
                      host_is_expected_public=host in ('taige.us', 'board.taige.us'),
                      path_is_root=parsed.path in ('', '/'), has_userinfo=parsed.username is not None or parsed.password is not None,
                      has_query=bool(parsed.query), has_fragment=bool(parsed.fragment))
        report['host_is_loopback'] = host == 'localhost'
        if host:
            try:
                address = ipaddress.ip_address(host)
                report['host_is_loopback'] = address.is_loopback or bool(getattr(address, 'ipv4_mapped', None) and address.ipv4_mapped.is_loopback)
            except ValueError:
                pass
        port = parsed.port
        report['port_class'] = 'default' if port is None else str(port) if port in (443, 7001) else 'other'
        report['parse_valid'] = bool(parsed.scheme and host) and not any(ord(c) < 32 or ord(c) == 127 for c in value)
    except Exception:
        pass
    return report


def agent_metadata():
    report = {'exists': False, 'regular_file': False, 'owner_root': False, 'private_permissions': False,
              'mode': None, 'uid': None, 'gid': None, 'group_readable': False,
              'group_or_world_writable': False, 'world_accessible': False,
              'classification': 'missing', 'json_object': False, 'exact_known_fields': False, 'field_names': [],
              'field_names_truncated': False, 'token_is_string': False, 'token_length': None, 'token_length_capped': False,
              'panel_url': panel_url_metadata(None)}
    try:
        info = AGENT.lstat()
        report.update(exists=True, regular_file=stat.S_ISREG(info.st_mode), owner_root=root_owned(info),
                      private_permissions=not bool(info.st_mode & 0o077), mode=format(stat.S_IMODE(info.st_mode), '04o'),
                      uid=info.st_uid, gid=info.st_gid, group_readable=bool(info.st_mode & 0o040),
                      group_or_world_writable=bool(info.st_mode & 0o022), world_accessible=bool(info.st_mode & 0o007))
        if not report['regular_file'] or not report['owner_root']:
            report['classification'] = 'unsafe_agent_file'
            return report
        fd = os.open(AGENT, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            opened = os.fstat(fd)
            if (not stat.S_ISREG(opened.st_mode) or not root_owned(opened)
                    or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino)):
                report['classification'] = 'agent_file_changed'
                return report
            if opened.st_size > 65536:
                report['classification'] = 'agent_file_too_large'
                return report
            with os.fdopen(fd, 'rb', closefd=False) as source:
                raw = source.read(65537)
            if len(raw) > 65536:
                report['classification'] = 'agent_file_too_large'
                return report
        finally:
            os.close(fd)
        try:
            data = parse_json(raw)
        except Exception:
            report['classification'] = 'agent_json_invalid'
            return report
        report['json_object'] = isinstance(data, dict)
        if not isinstance(data, dict):
            report['classification'] = 'agent_not_object'
            return report
        report['exact_known_fields'] = set(data) == {'panel_url', 'token'}
        names = sorted({key if FIELD_NAME.fullmatch(key) else 'unknown' for key in data})
        report['field_names'], report['field_names_truncated'] = names[:32], len(names) > 32
        token = data.get('token')
        report['token_is_string'] = isinstance(token, str)
        if report['token_is_string']:
            report['token_length'] = min(len(token), 512)
            report['token_length_capped'] = len(token) > 512
        report['panel_url'] = panel_url_metadata(data.get('panel_url'))
        report['classification'] = 'inspected'
        return report
    except FileNotFoundError:
        return report
    except PermissionError:
        report['classification'] = 'agent_permission_denied'
        return report
    except Exception:
        report['classification'] = 'agent_inspection_failed'
        return report


def secure_parents(path, resolved):
    for parent in set((*path.parents, *resolved.parents)):
        info = parent.stat()
        if not stat.S_ISDIR(info.st_mode) or not root_owned(info) or info.st_mode & 0o022:
            return False
    return True


def binary_metadata(name):
    # name comes only from the fixed compiled-in tuple; never a source/control.
    report = {'path': name, 'exists': False, 'is_symlink': False, 'regular_file': False, 'owner_root': False,
              'safe_permissions': False, 'safe_parents': False, 'sha256': None, 'classification': 'missing'}
    try:
        path = Path(name)
        initial = path.lstat()
        report.update(exists=True, is_symlink=stat.S_ISLNK(initial.st_mode))
        resolved = path.resolve(strict=True)
        info = resolved.stat()
        report.update(regular_file=stat.S_ISREG(info.st_mode), owner_root=root_owned(info),
                      safe_permissions=not bool(info.st_mode & 0o022) and bool(info.st_mode & 0o111),
                      safe_parents=secure_parents(path, resolved))
        if not all(report[key] for key in ('regular_file', 'owner_root', 'safe_permissions', 'safe_parents')):
            report['classification'] = 'unsafe_binary'
            return report
        if not 0 < info.st_size <= 256 * 1024 * 1024:
            report['classification'] = 'binary_size_invalid'
            return report
        fd = os.open(resolved, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            current = os.fstat(fd)
            if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) != (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns):
                report['classification'] = 'binary_changed'
                return report
            hasher, total = hashlib.sha256(), 0
            with os.fdopen(fd, 'rb', closefd=False) as source:
                while True:
                    chunk = source.read(1048576)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > 256 * 1024 * 1024:
                        report['classification'] = 'binary_size_invalid'
                        return report
                    hasher.update(chunk)
            after = os.fstat(fd)
            if (after.st_size, after.st_mtime_ns) != (current.st_size, current.st_mtime_ns) or total != current.st_size:
                report['classification'] = 'binary_changed'
                return report
            report.update(sha256=hasher.hexdigest(), classification='inspected')
        finally:
            os.close(fd)
    except FileNotFoundError:
        report['classification'] = 'dangling_binary_link' if report['is_symlink'] else 'missing'
    except PermissionError:
        report['classification'] = 'binary_permission_denied'
    except Exception:
        report['classification'] = 'binary_inspection_failed'
    return report


def command_output(arguments):
    try:
        result = subprocess.run(arguments, capture_output=True, timeout=5)
        if result.returncode != 0:
            return None, 'command_failed'
        if len(result.stdout) > 1024 * 1024:
            return None, 'command_output_too_large'
        return result.stdout, 'ok'
    except FileNotFoundError:
        return None, 'command_unavailable'
    except subprocess.TimeoutExpired:
        return None, 'command_timeout'
    except Exception:
        return None, 'command_failed'


def unit_metadata(unit):
    body, classification = command_output(['systemctl', 'show', unit, '--property=' + ','.join(PROPERTIES), '--no-pager'])
    report = {'unit': unit, 'classification': classification, 'properties': {key: None for key in PROPERTIES}}
    if body is None:
        return report
    try:
        for line in body.decode('utf-8').splitlines():
            if '=' not in line:
                continue
            key, value = line.split('=', 1)
            if key not in PROPERTIES:
                continue
            valid = ((key == 'ActiveState' and value in ACTIVE_VALUES) or (key == 'SubState' and value in SUB_VALUES)
                     or (key == 'Result' and value in RESULT_VALUES)
                     or (key == 'TimeoutStartUSec' and len(value) <= 64 and DURATION.fullmatch(value)))
            report['properties'][key] = value if valid else 'unknown'
    except Exception:
        report['classification'] = 'unit_output_invalid'
        report['properties'] = {key: None for key in PROPERTIES}
    return report


def probe_service_metadata(agent):
    body, classification = command_output(['systemctl', 'show', PROBE_UNIT,
                                           '--property=' + ','.join(PROBE_PROPERTIES), '--no-pager'])
    report = {'unit': PROBE_UNIT, 'classification': classification,
              'properties': {key: None for key in PROBE_PROPERTIES},
              'identity_resolved': False, 'static_identity': False, 'effective_uid': None, 'effective_gid': None,
              'user_matches_file_owner': False, 'group_matches_file_group': False,
              'group_read_matches_service': False, 'agent_read_policy_compatible': False}
    if body is None:
        return report
    try:
        fields = {}
        for line in body.decode('utf-8').splitlines():
            key, separator, value = line.partition('=')
            if not separator or key not in PROBE_PROPERTIES or key in fields:
                raise ValueError()
            fields[key] = value
            valid = ((key == 'LoadState' and value in ('loaded', 'not-found', 'error', 'masked', 'merged', 'stub', 'bad-setting'))
                     or (key in ('User', 'Group') and (value == '' or ACCOUNT_NAME.fullmatch(value)))
                     or (key == 'DynamicUser' and value in ('yes', 'no'))
                     or (key == 'ActiveState' and value in ACTIVE_VALUES)
                     or (key == 'SubState' and value in SUB_VALUES)
                     or (key == 'Result' and value in RESULT_VALUES))
            report['properties'][key] = value if valid else 'unknown'
        if set(fields) != set(PROBE_PROPERTIES):
            raise ValueError()
        report['static_identity'] = fields['LoadState'] == 'loaded' and fields['DynamicUser'] == 'no'
        user, group = fields['User'] or 'root', fields['Group']
        if not ACCOUNT_NAME.fullmatch(user) or (group and not ACCOUNT_NAME.fullmatch(group)):
            raise ValueError()
        account = pwd.getpwuid(int(user)) if user.isdecimal() else pwd.getpwnam(user)
        gid = (grp.getgrgid(int(group)).gr_gid if group.isdecimal() else grp.getgrnam(group).gr_gid) if group else account.pw_gid
        if account.pw_uid < 0 or gid < 0:
            raise ValueError()
        report.update(identity_resolved=True, effective_uid=account.pw_uid, effective_gid=gid,
                      user_matches_file_owner=account.pw_uid == agent['uid'], group_matches_file_group=gid == agent['gid'])
        report['group_read_matches_service'] = bool(report['static_identity'] and report['group_matches_file_group']
                                                    and agent['group_readable'])
        report['agent_read_policy_compatible'] = bool(agent['regular_file'] and agent['owner_root'] and
            (agent['mode'] == '0600' or (agent['mode'] == '0640' and report['group_read_matches_service'])))
    except Exception:
        report['classification'] = 'probe_identity_unresolved'
    return report


def ipv6_metadata():
    result = {}
    for kind, arguments in (('default_route', ['ip', '-6', '-j', 'route', 'show', 'default']),
                            ('global_address', ['ip', '-6', '-j', 'address', 'show', 'scope', 'global'])):
        body, classification = command_output(arguments)
        entry = {'classification': classification, 'present': False}
        if body is not None:
            try:
                values = parse_json(body)
                if not isinstance(values, list):
                    raise ValueError()
                if kind == 'default_route':
                    entry['present'] = any(isinstance(row, dict) and row.get('dst') in ('default', '::/0') for row in values)
                else:
                    entry['present'] = any(isinstance(info, dict) and info.get('family') == 'inet6' and info.get('scope') == 'global'
                                           for row in values if isinstance(row, dict) for info in row.get('addr_info', []))
            except Exception:
                entry['classification'] = 'network_output_invalid'
                entry['present'] = False
        result[kind] = entry
    return result


def inspect_environment():
    agent = agent_metadata()
    return {'status': 'inspected', 'schema': 1, 'agent': agent, 'probe_service': probe_service_metadata(agent),
            'binaries': [binary_metadata(path) for path in BINARY_PATHS],
            'guard': [unit_metadata(unit) for unit in UNITS], 'ipv6': ipv6_metadata(),
            'files_mutated': False, 'policy_mutated': False, 'network_mutated': False, 'binaries_executed': False}


def main(argv=None):
    if (sys.argv[1:] if argv is None else argv):
        print('{"status":"error","reason":"invalid_arguments"}', flush=True)
        return 1
    if os.geteuid() != 0:
        print('{"status":"error","reason":"root_required"}', flush=True)
        return 1
    try:
        report = inspect_environment()
    except Exception:
        print('{"status":"error","reason":"environment_inspection_failed"}', flush=True)
        return 1
    print(json.dumps(report, sort_keys=True), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

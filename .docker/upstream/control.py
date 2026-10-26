#!/usr/bin/env python3
"""Validate the finite, non-secret workflow control envelope before execution."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

SIBLING = Path(__file__).resolve().parent
OPERATIONS = {'accept-source-address', 'inspect-environment', 'prepare', 'audit-scope', 'restore-scope', 'snapshot', 'verify-success', 'verify-withdrawn', 'verify-baseline',
              'withdraw', 'apply_hidden', 'publish', 'rollback'}


def parse(raw):
    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate_control_key')
            result[key] = value
        return result
    if len(raw) > 16384:
        raise ValueError('control_too_large')
    return json.loads(raw, object_pairs_hook=unique)


def validate(value):
    if not isinstance(value, dict) or set(value) != {'operation', 'plan_id', 'plan_sha256', 'selection', 'execution_id'}:
        raise ValueError('control_fields_invalid')
    operation = value['operation']
    if operation not in OPERATIONS:
        raise ValueError('operation_invalid')
    selection = value['selection']
    if not isinstance(selection, dict) or len(selection) > 41:
        raise ValueError('selection_invalid')
    for key, commitment in selection.items():
        if not re.fullmatch(r'U(?:0[1-9]|[1-3][0-9]|4[01])', key) or (commitment is not None and
                (not isinstance(commitment, str) or not re.fullmatch('[a-f0-9]{64}', commitment))):
            raise ValueError('selection_invalid')
    if operation in ('prepare', 'audit-scope', 'inspect-environment'):
        if value['plan_id'] != '' or value['plan_sha256'] != '' or selection:
            raise ValueError('prepare_arguments_invalid')
    else:
        if not isinstance(value['plan_id'], str) or not re.fullmatch('[a-f0-9]{32}', value['plan_id']) or not isinstance(value['plan_sha256'], str) or not re.fullmatch('[a-f0-9]{64}', value['plan_sha256']):
            raise ValueError('plan_binding_invalid')
        if (operation in ('snapshot', 'restore-scope')) != (not selection):
            raise ValueError('selection_required')
    if operation in ('verify-success', 'verify-withdrawn'):
        if not isinstance(value['execution_id'], str) or not re.fullmatch('[a-f0-9]{64}', value['execution_id']):
            raise ValueError('execution_binding_required')
    elif value['execution_id'] != '':
        raise ValueError('unexpected_execution_binding')
    return value


def command(value, quic_sha=None):
    validate(value)
    operation = value['operation']
    if operation == 'inspect-environment':
        return [sys.executable, str(SIBLING/'inspect_environment.py')]
    if operation == 'audit-scope':
        return [sys.executable, str(SIBLING/'scope_restore.py'), 'audit']
    if operation == 'prepare':
        if not isinstance(quic_sha, str) or not re.fullmatch('[a-f0-9]{64}', quic_sha):
            raise ValueError('observer_binding_invalid')
        return [sys.executable, str(SIBLING/'prepare.py'), '--quic-observer-sha256', quic_sha]
    binding = ['--plan-id', value['plan_id'], '--plan-sha256', value['plan_sha256']]
    if operation == 'restore-scope':
        return [sys.executable, str(SIBLING/'scope_restore.py'), 'restore', *binding]
    if operation == 'snapshot':
        return [sys.executable, str(SIBLING/'public_verify.py'), 'snapshot', *binding]
    if operation == 'accept-source-address':
        if set(value['selection']) != {'U01'} or value['selection']['U01'] is None:
            raise ValueError('source_selection_invalid')
        return [sys.executable, str(SIBLING/'accept_source_address.py'), *binding, '--key', 'U01',
                '--expected-source-sha256', value['selection']['U01']]
    if operation.startswith('verify-'):
        keys = [item for key in sorted(value['selection']) for item in ['--key', key]]
        if operation == 'verify-baseline':
            return [sys.executable, str(SIBLING/'public_verify.py'), 'baseline', *binding, *keys]
        return [sys.executable, str(SIBLING/'public_verify.py'), 'verify', *binding,
                '--execution-plan-id', value['execution_id'], '--expect', operation.removeprefix('verify-'), *keys]
    return [sys.executable, str(SIBLING/'maintain.py'), *binding, '--operation', operation,
            '--selection-json', json.dumps(value['selection'], sort_keys=True, separators=(',', ':'))]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--from-env', action='store_true')
    parser.add_argument('--quic-sha256')
    args = parser.parse_args()
    if args.from_env:
        value = validate({'operation': os.environ['OPERATION'], 'plan_id': os.environ['PLAN_ID'],
                          'plan_sha256': os.environ['PLAN_SHA256'], 'selection': parse(os.environ['SELECTION']),
                          'execution_id': os.environ['EXECUTION_ID']})
        print(json.dumps(value, sort_keys=True, separators=(',', ':')))
        return 0
    value = validate(parse(sys.stdin.buffer.read(16385)))
    return subprocess.run(command(value, args.quic_sha256), check=False).returncode


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, TypeError, KeyError):
        print('{"status":"rejected","reason":"invalid_control"}', flush=True)
        raise SystemExit(1)

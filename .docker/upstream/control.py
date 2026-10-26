#!/usr/bin/env python3
"""Validate the finite, non-secret workflow control envelope before execution."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

SIBLING = Path(__file__).resolve().parent
OPERATIONS = {'recipient', 'import-reviewed', 'secure-probe-config', 'accept-source-address', 'inspect-environment', 'prepare', 'audit-scope', 'restore-scope', 'snapshot', 'verify-success', 'verify-withdrawn', 'verify-baseline',
              'withdraw', 'apply_hidden', 'publish', 'rollback'}
MAX_CONTROL = 65535


def parse(raw):
    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('duplicate_control_key')
            result[key] = value
        return result
    if len(raw.encode() if isinstance(raw, str) else raw) > MAX_CONTROL:
        raise ValueError('control_too_large')
    return json.loads(raw, object_pairs_hook=unique)


def validate(value):
    fields = {'operation', 'plan_id', 'plan_sha256', 'selection', 'execution_id'}
    if not isinstance(value, dict) or set(value) not in (fields, fields | {'ciphertext'}):
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
    if operation in ('prepare', 'audit-scope', 'inspect-environment', 'secure-probe-config'):
        if value['plan_id'] != '' or value['plan_sha256'] != '' or selection:
            raise ValueError('prepare_arguments_invalid')
    else:
        if not isinstance(value['plan_id'], str) or not re.fullmatch('[a-f0-9]{32}', value['plan_id']) or not isinstance(value['plan_sha256'], str) or not re.fullmatch('[a-f0-9]{64}', value['plan_sha256']):
            raise ValueError('plan_binding_invalid')
        if (operation in ('snapshot', 'restore-scope', 'recipient', 'import-reviewed')) != (not selection):
            raise ValueError('selection_required')
    if operation in ('verify-success', 'verify-withdrawn'):
        if not isinstance(value['execution_id'], str) or not re.fullmatch('[a-f0-9]{64}', value['execution_id']):
            raise ValueError('execution_binding_required')
    elif value['execution_id'] != '':
        raise ValueError('unexpected_execution_binding')
    ciphertext = value.get('ciphertext', {})
    if operation == 'import-reviewed':
        try:
            spec = importlib.util.spec_from_file_location('control_reviewed_import', SIBLING/'import_reviewed.py')
            module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
            module.payload_envelope(json.dumps(ciphertext, sort_keys=True, separators=(',', ':'), allow_nan=False).encode(),
                                    value['plan_id'], value['plan_sha256'])
        except Exception as error:
            raise ValueError('ciphertext_invalid') from error
    elif ciphertext != {}:
        raise ValueError('unexpected_ciphertext')
    return value


def command(value, quic_sha=None):
    validate(value)
    operation = value['operation']
    if operation == 'secure-probe-config':
        return [sys.executable, str(SIBLING/'secure_probe_config.py')]
    if operation == 'inspect-environment':
        return [sys.executable, str(SIBLING/'inspect_environment.py')]
    if operation == 'audit-scope':
        return [sys.executable, str(SIBLING/'scope_restore.py'), 'audit']
    if operation == 'prepare':
        if not isinstance(quic_sha, str) or not re.fullmatch('[a-f0-9]{64}', quic_sha):
            raise ValueError('observer_binding_invalid')
        return [sys.executable, str(SIBLING/'prepare.py'), '--quic-observer-sha256', quic_sha]
    binding = ['--plan-id', value['plan_id'], '--plan-sha256', value['plan_sha256']]
    if operation in ('recipient', 'import-reviewed'):
        return [sys.executable, str(SIBLING/'import_reviewed.py'),
                'recipient' if operation == 'recipient' else 'import', *binding]
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


def execute(value, quic_sha=None):
    args = command(value, quic_sha)
    body = (json.dumps(value['ciphertext'], sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
            if value['operation'] == 'import-reviewed' else None)
    return subprocess.run(args, input=body, check=False).returncode


def from_environment():
    names = ('OPERATION', 'PLAN_ID', 'PLAN_SHA256', 'SELECTION', 'EXECUTION_ID', 'CIPHERTEXT')
    fields = ('operation', 'plan_id', 'plan_sha256', 'selection', 'execution_id', 'ciphertext')
    inputs = {field: os.environ.get(name, '{}') if name == 'CIPHERTEXT' else os.environ[name]
              for field, name in zip(fields, names)}
    # Conservative serialized-input bound includes quotes/escaping in the
    # workflow_dispatch string field, not merely the decrypted JSON envelope.
    if len(json.dumps(inputs, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()) > MAX_CONTROL:
        raise ValueError('dispatch_inputs_too_large')
    inputs['selection'] = parse(inputs['selection']); inputs['ciphertext'] = parse(inputs['ciphertext'])
    return validate(inputs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--from-env', action='store_true')
    parser.add_argument('--quic-sha256')
    args = parser.parse_args()
    if args.from_env:
        value = from_environment()
        print(json.dumps(value, sort_keys=True, separators=(',', ':')))
        return 0
    value = validate(parse(sys.stdin.buffer.read(MAX_CONTROL+1)))
    return execute(value, args.quic_sha256)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, TypeError, KeyError):
        print('{"status":"rejected","reason":"invalid_control"}', flush=True)
        raise SystemExit(1)

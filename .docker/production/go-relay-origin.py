#!/usr/bin/env python3
"""Reuse guarded origin operations for the owned Go vhost only."""
import importlib.util
from pathlib import Path
import sys

SPEC = importlib.util.spec_from_file_location('go_origin_base', Path(__file__).with_name('website-relay-origin.py'))
origin = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(origin)
origin.DOMAIN = 'capybarago.uk'
origin.CONFIG = Path('/etc/nginx/sites-enabled/capybarago.uk.conf')
origin.RENEWAL = Path('/etc/letsencrypt/renewal/capybarago.uk.conf')
origin.BASELINE_SHA256 = '3572ede7e0d5034289744ff2ff40698969b5d827920882c021a2ffc9f56adee7'
origin.DEFAULT_CHANGE_ID = '20261102-capybara-go-relay'


def build_candidate(before):
    origin.require(origin.digest(before) == origin.BASELINE_SHA256, 'origin_baseline_sha_mismatch')
    source = before.decode()
    origin.require(len(list(origin.matching_servers(origin.parse(source)))) == 2, 'unexpected_go_servers')
    origin.require('set_real_ip_from 155.103.118.155;' not in source, 'relay_already_trusted')
    origin.require('real_ip_header CF-Connecting-IP;' in source and 'real_ip_recursive off;' in source, 'unexpected_real_ip_mode')
    origin.require('proxy_set_header X-Forwarded-For $remote_addr;' in source, 'unsafe_forwarded_chain')
    origin.require('qiyun-cdn' not in source, 'unexpected_node_include')
    return origin.replace_exact(source, '    set_real_ip_from 173.245.48.0/20;', '    set_real_ip_from 155.103.118.155;\n    set_real_ip_from 173.245.48.0/20;').encode()


origin.build_candidate = build_candidate
if __name__ == '__main__':
    sys.exit(origin.main())

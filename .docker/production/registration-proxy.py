#!/usr/bin/env python3
"""Scoped, SHA-guarded identity fixes. Run on the indicated host, never globally."""
import argparse
import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location('relay_base', Path(__file__).with_name('website-relay-origin.py'))
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
BOARD_SHA = 'e2f2991ff8240019ccbf0080eff94ffdf466a659d4ca40db79750c28da7ca7da'
RELAY_SHA = '9cfef765dd98c7394da9908879c0ed2e7aafac635d358ff8b1069180317b30e4'
CHANGE = 'registration-20261103'


def candidate(before, target):
    base.require(base.digest(before) == (BOARD_SHA if target == 'board' else RELAY_SHA), 'baseline_changed')
    source = before.decode()
    base.require('set_real_ip_from' not in source and 'real_ip_header' not in source, 'unexpected_existing_trust')
    trust = '    # Registration protection: accept client identity only from Cloudflare peers.\n'
    trust += ''.join('    set_real_ip_from '+net+';\n' for net in base.CF_NETWORKS)
    trust += '    real_ip_header CF-Connecting-IP;\n    real_ip_recursive off;\n\n'
    anchor = '    ssl_certificate ' + ('/etc/nginx/ssl/board.taige.us/fullchain.pem;' if target == 'board' else '/etc/letsencrypt/live/taige.us/fullchain.pem;')
    source = base.replace_exact(source, anchor, trust+anchor)
    if target == 'board':
        source = base.replace_exact(source, 'proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;', 'proxy_set_header X-Forwarded-For $remote_addr;')
        source = base.replace_exact(source, '        proxy_set_header X-Forwarded-Proto https;', '''        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header X-Forwarded-Host board.taige.us;
        proxy_set_header X-Forwarded-Port 443;
        proxy_set_header CF-Connecting-IP $remote_addr;
        proxy_set_header Forwarded "";
        proxy_set_header True-Client-IP "";''')
    # Parser validation and unchanged HTTP redirect/ACME and other upstream nodes.
    old = base.parse(before.decode()); new = base.parse(source)
    base.require(len(old) == len(new) and old[:-1] == new[:-1], 'unrelated_block_changed')
    return source.encode()


def configure(target):
    base.DOMAIN = 'board.taige.us' if target == 'board' else 'taige.us'
    base.CONFIG = Path('/etc/nginx/sites-enabled/board.taige.us.conf' if target == 'board' else '/etc/nginx/sites-enabled/taige.us')
    base.BACKUPS = Path('/root/xboard-backups/registration-proxy/'+target)
    base.BASELINE_SHA256 = BOARD_SHA if target == 'board' else RELAY_SHA
    base.build_candidate = lambda before: candidate(before, target)


def main():
    p=argparse.ArgumentParser();p.add_argument('target',choices=['board','relay']);p.add_argument('operation',choices=['inspect','prepare','apply','rollback'])
    a=p.parse_args();configure(a.target)
    with base.operation_lock():
        if a.operation == 'inspect':
            result={'target':a.target,'sha256':base.digest(base.current_config())}
        elif a.operation == 'prepare': result=base.prepare(CHANGE)
        else: result=base.apply_change(CHANGE,a.operation=='rollback')
    print(json.dumps(result,sort_keys=True))

if __name__ == '__main__': main()

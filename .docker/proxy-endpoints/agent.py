#!/usr/bin/env python3
"""Fixed-port authorization agent. No shell commands or unbounded offline grants."""
import argparse
import ipaddress
import grp
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request

ROOT = Path('/etc/xboard-proxy-endpoints')
PORTS = set(range(20001, 20011))
HOSTS = {'216.36.108.173', '192.204.56.29'}

def run(args, check=True):
    return subprocess.run(args, check=check, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)

def service(port):
    if type(port) is not int or port not in PORTS:
        raise ValueError('invalid_port')
    return 'xboard-proxy-port@%d.service' % port

def validate(payload, address):
    if payload.get('address') != address or address not in HOSTS:
        raise ValueError('wrong_host')
    now = payload['server_time']; until = payload['lease_until']
    if type(now) is not int or type(until) is not int or not 0 < until-now <= 120:
        raise ValueError('invalid_lease')
    rows = payload['endpoints']
    if len(rows) != 10 or {r['port'] for r in rows} != PORTS or len({r['id'] for r in rows}) != 10:
        raise ValueError('invalid_inventory')
    for row in rows:
        if type(row['id']) is not int or row['id'] < 1 or type(row['revision']) is not int or row['revision'] < 1 or type(row['enabled']) is not bool:
            raise ValueError('invalid_revision')
        if row['enabled']:
            creds = row['credentials']
            if type(row['expires_at']) is not int or row['expires_at'] <= now:
                raise ValueError('invalid_expiry')
            for key in ['username', 'password']:
                value = creds[key]
                if not isinstance(value,str) or not 8 <= len(value) <= 128 or not all(c.isascii() and (c.isalnum() or c in '_-') for c in value):
                    raise ValueError('invalid_credentials')
    return rows

def configuration(row):
    return {'log': {'level':'fatal'}, 'inbounds':[{'type':'mixed','tag':'proxy','listen':'127.0.0.1',
        'listen_port': row['port']+1000, 'users':[row['credentials']]}],
        'outbounds':[{'type':'direct','tag':'direct'}],
        'route':{'rules':[{'ip_is_private':True,'action':'reject'},
            {'ip_cidr':[ip+'/32' for ip in sorted(HOSTS)],'action':'reject'},
            {'network':'udp','action':'reject'}], 'final':'direct'}}

def grant_deadline(payload, row, started):
    return started + min(payload['lease_until'], row['expires_at']) - payload['server_time'] if row['enabled'] else 0

def revoke():
    for port in sorted(PORTS): run(['systemctl','stop',service(port)],False)

def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--revoke',action='store_true'); args=parser.parse_args()
    if args.revoke: revoke(); return
    settings=json.loads((ROOT/'agent.json').read_text())
    certificate = None
    if settings.get('enrolled'):
        address = ipaddress.IPv4Address(settings['address'])
        if not address.is_global or address.is_multicast:
            raise ValueError('invalid_enrolled_address')
        HOSTS.add(str(address))
        certificate = Path('/etc/xboard-px-transport/server.crt').read_text()
    if settings['url'] not in ['https://capybarago.uk/api/v1/proxy-agent/sync','https://capybarahub.fyi/api/v1/proxy-agent/sync'] or settings['address'] not in HOSTS:
        raise ValueError('invalid_agent_settings')
    core = '/usr/bin/sing-box' if Path('/usr/bin/sing-box').is_file() else '/usr/local/lib/xboard-proxy-endpoints/sing-box'
    active={}; reports=[]; deadlines={}; next_poll=0
    revoke()  # Never trust cached credentials after an agent restart.
    try:
        while True:
            tick=time.monotonic()
            for port, deadline in list(deadlines.items()):
                if tick >= deadline:
                    run(['systemctl','stop',service(port)],False); active.pop(port,None); deadlines.pop(port,None)
            if tick >= next_poll:
                next_poll=tick+20
                try:
                    request=urllib.request.Request(settings['url'],data=json.dumps({'reports':reports, 'certificate':certificate}).encode(),
                        headers={'Authorization':'Bearer '+settings['token'],'Content-Type':'application/json'},method='POST')
                    # Explicit no-redirect transport keeps the host token on the configured origin.
                    class NoRedirect(urllib.request.HTTPRedirectHandler):
                        def redirect_request(self,*args,**kwargs): return None
                    started=time.monotonic()
                    with urllib.request.build_opener(NoRedirect()).open(request,timeout=10) as response:
                        raw=response.read(65537)
                        if len(raw)>65536: raise ValueError('oversized_snapshot')
                    payload=json.loads(raw); rows=validate(payload,settings['address'])
                    updated=[]
                    for row in rows:
                        port=row['port']; enabled=row['enabled']
                        deadline=grant_deadline(payload,row,started)
                        enabled=enabled and deadline>time.monotonic()
                        fingerprint=json.dumps(row['credentials'],sort_keys=True)
                        try:
                            if enabled:
                                path=ROOT/('port-%d.json'%port)
                                if active.get(port)!=fingerprint or run(['systemctl','is-active','--quiet',service(port)],False).returncode:
                                    temporary=path.with_suffix('.tmp'); temporary.write_text(json.dumps(configuration(row)))
                                    os.chmod(temporary,0o640);os.chown(temporary,0,grp.getgrnam('xboard-proxy').gr_gid)
                                    run([core,'check','-c',str(temporary)])
                                    temporary.replace(path);run(['systemctl','restart',service(port)])
                                    run(['systemctl','is-active','--quiet',service(port)])
                                    active[port]=fingerprint
                                deadlines[port]=deadline
                            else:
                                run(['systemctl','stop',service(port)],False);active.pop(port,None);deadlines.pop(port,None)
                            updated.append({'id':row['id'],'revision':row['revision'],'running':bool(enabled)})
                        except Exception:
                            run(['systemctl','stop',service(port)],False);active.pop(port,None);deadlines.pop(port,None)
                            updated.append({'id':row['id'],'revision':row['revision'],'running':False})
                    reports=updated
                except Exception:
                    # Do not print request, credentials, response or tokens to journald.
                    print('authorization_sync_failed',flush=True)
            time.sleep(1)
    finally:
        revoke()

if __name__=='__main__': main()

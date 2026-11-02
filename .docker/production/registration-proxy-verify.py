#!/usr/bin/env python3
"""Verify installed vhosts through public DNS and direct/relay spoof attempts.

Run only on the origin. Temporary random diagnostic locations are source-IP
restricted, never print request identifiers or client addresses, and are removed
in finally. No application routes, account writes, or messages are involved.
"""
import importlib.util
import json
import queue
import secrets
import stat
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

spec=importlib.util.spec_from_file_location('base',Path(__file__).with_name('website-relay-origin.py'))
b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
SPOOF=('X-Forwarded-For: 198.51.100.27','CF-Connecting-IP: 203.0.113.38','X-Forwarded-Host: spoof.invalid','X-Forwarded-Proto: http','X-Forwarded-Port: 80','Forwarded: for=198.51.100.27','True-Client-IP: 203.0.113.38')

def verify(domain):
    b.DOMAIN=domain;b.CONFIG=Path('/etc/nginx/sites-enabled/'+domain+'.conf')
    before=b.current_config();source=before.decode();metadata=b.CONFIG.stat()
    state={'mode':stat.S_IMODE(metadata.st_mode),'uid':metadata.st_uid,'gid':metadata.st_gid}
    servers=list(b.matching_servers(b.parse(source)))
    tls=next(node for node in servers if any(n['name']=='listen' and '443' in ' '.join(n['args']) for n in node['children']))
    root=next(n for n in tls['children'] if n['name']=='location' and n['args']==['/'])
    headers=[n for n in root['children'] if n['name']=='proxy_set_header' and n['args'][0].lower() not in {'upgrade','connection'}]
    nonce=secrets.token_hex(24);endpoint='/__xboard_guard_'+nonce;received=queue.Queue()
    class Receiver(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path!=endpoint or self.headers.get('X-Xboard-Diagnostic')!=nonce:
                self.send_error(404);return
            received.put({h:self.headers.get(h,'') for h in ('host','x-real-ip','x-forwarded-for','x-forwarded-host','x-forwarded-proto','x-forwarded-port','cf-connecting-ip','forwarded','true-client-ip')})
            self.send_response(200);self.end_headers();self.wfile.write(b'guard-identity-ok')
        def log_message(self,*args): pass
    receiver=ThreadingHTTPServer(('127.0.0.1',0),Receiver);thread=threading.Thread(target=receiver.serve_forever,daemon=True);thread.start()
    diagnostic='\n    location = '+endpoint+' {\n        allow 127.0.0.1;\n        allow '+b.ORIGIN+';\n        deny all;\n        access_log off;\n        error_log /dev/null crit;\n        proxy_pass http://127.0.0.1:'+str(receiver.server_address[1])+';\n'
    diagnostic+=''.join('        proxy_set_header '+' '.join(n['args'])+';\n' for n in headers)
    diagnostic+='        proxy_set_header X-Xboard-Diagnostic '+nonce+';\n    }\n'
    position=source.rfind('}');temporary=(source[:position]+diagnostic+source[position:]).encode();changed=False;samples=[]
    try:
        b.activate_with_recovery(before,temporary,state);changed=True
        modes=[('public_dns',None,b.ORIGIN),('direct_spoof','127.0.0.1','127.0.0.1')]
        if domain!='board.taige.us': modes.append(('relay_spoof',b.RELAY,b.ORIGIN))
        for name,address,expected in modes:
            cmd=['curl','--noproxy','*','-fsS','--connect-timeout','8','--max-time','25']
            if address: cmd+=['--resolve',domain+':443:'+address]
            # Board uses a Cloudflare origin certificate. Trust that exact local
            # certificate for the local probe; never disable TLS verification.
            if domain=='board.taige.us' and address=='127.0.0.1': cmd+=['--cacert','/etc/nginx/ssl/board.taige.us/fullchain.pem']
            for h in SPOOF: cmd+=['-H',h]
            cmd+=['https://'+domain+endpoint]
            result=None
            for attempt in range(4):
                result=subprocess.run(cmd,capture_output=True,text=True,timeout=30)
                if result.returncode==0: break
                if attempt<3: b.time.sleep(0.5)
            b.require(result.returncode==0 and result.stdout=='guard-identity-ok','probe_failed_'+domain+'_'+name)
            received_headers=received.get(timeout=5)
            b.require(received_headers['x-forwarded-for']==expected and received_headers['x-real-ip']==expected,'identity_mismatch_'+domain+'_'+name)
            b.require(not received_headers['forwarded'] and not received_headers['true-client-ip'],'spoofed_headers_preserved')
            samples.append({'name':name,'headers':received_headers,'expected':expected})
        return {'domain':domain,'assertions':b.laravel_assertions(samples)}
    finally:
        if changed:
            b.require(b.current_config()==temporary,'cleanup_config_conflict')
            b.install_config(before,state);b.checked(['nginx','-t'],'cleanup_nginx_invalid');b.checked(['systemctl','reload','nginx'],'cleanup_reload_failed')
        receiver.shutdown();receiver.server_close();thread.join(timeout=5)
        b.require(b.current_config()==before and not thread.is_alive(),'cleanup_failed')

if __name__=='__main__':
    with b.operation_lock():
        for domain in ('capybarago.uk','taige.us','board.taige.us'):
            print(json.dumps(verify(domain)),flush=True)
    print(json.dumps({'diagnostics_cleaned':True}))

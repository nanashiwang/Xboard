#!/usr/bin/env python3
"""One-time conversion of the authorized ten-port service to leased authentication."""
import json, os, shutil, subprocess, time
from pathlib import Path
ROOT=Path('/etc/xboard-proxy-endpoints')
def run(*args): subprocess.run(args,check=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
def main():
    config=ROOT/'agent.json'
    if not config.is_file() or (config.stat().st_mode&0o077): raise RuntimeError('agent_config_must_be_private')
    data=json.loads(config.read_text())
    if data['address'] not in ['216.36.108.173','192.204.56.29']: raise RuntimeError('wrong_host')
    backup=Path('/root/xboard-proxy-agent-backup-'+str(int(time.time())));backup.mkdir(mode=0o700)
    for name in ['xboard-proxy-endpoints.service','xboard-proxy-auth.service']:
        shutil.copy2('/etc/systemd/system/'+name,backup/name)
    shutil.copy2(ROOT/'auth.json',backup/'auth.json')
    shutil.copy2(Path(__file__).with_name('agent.py'),ROOT/'agent.py');os.chmod(ROOT/'agent.py',0o700)
    forward=Path('/etc/systemd/system/xboard-proxy-endpoints.service')
    content=forward.read_text().replace('After=network-online.target xboard-proxy-auth.service','After=network-online.target').replace('Requires=xboard-proxy-auth.service\n','')
    forward.write_text(content)
    Path('/etc/systemd/system/xboard-proxy-port@.service').write_text('''[Unit]
Description=Xboard leased proxy authentication %i
BindsTo=xboard-proxy-agent.service
After=network-online.target xboard-proxy-agent.service
[Service]
User=xboard-proxy-auth
Group=xboard-proxy
ExecStart=/usr/bin/sing-box run -c /etc/xboard-proxy-endpoints/port-%i.json
Restart=no
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
RestrictAddressFamilies=AF_INET AF_UNIX AF_NETLINK
CapabilityBoundingSet=
UMask=0077
''')
    Path('/etc/systemd/system/xboard-proxy-agent.service').write_text('''[Unit]
Description=Xboard proxy authorization lease agent
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
ExecStart=/usr/bin/python3 /etc/xboard-proxy-endpoints/agent.py
ExecStopPost=/usr/bin/python3 /etc/xboard-proxy-endpoints/agent.py --revoke
Restart=always
RestartSec=5
UMask=0077
TimeoutStopSec=30
[Install]
WantedBy=multi-user.target
''')
    run('systemctl','daemon-reload')
    run('systemctl','disable','--now','xboard-proxy-auth.service')
    run('systemctl','enable','--now','xboard-proxy-agent.service')
    run('systemctl','restart','xboard-proxy-endpoints.service')
    run('systemctl','is-active','--quiet','xboard-proxy-agent.service','xboard-proxy-endpoints.service')
    print('agent_installed; inventory remains controlled by the website')
if __name__=='__main__':main()

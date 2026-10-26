#!/usr/bin/env python3
"""Install only the restricted certificate worker; no relay or network changes."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import stat
import subprocess
import sys

SOURCE=Path(__file__).resolve().parent
TARGET=Path('/opt/xboard-identity-worker')
HOME=Path('/var/lib/xboard-identity')
FILES=('guard.py','entry_identity.py','allocation.json')
COMMAND='/usr/bin/env -i PATH=/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 /usr/bin/timeout 40s /usr/bin/python3 -E -s /opt/xboard-identity-worker/entry_identity.py'


def require(ok,code):
    if not ok:raise ValueError(code)


def hashes(path):return {n:hashlib.sha256((path/n).read_bytes()).hexdigest() for n in FILES}


def validate_key(public):
    require(isinstance(public,str) and re.fullmatch(r'ssh-ed25519 [A-Za-z0-9+/]{68} xboard-runtime-identity-20261027',public),'invalid_public_key')
    blob=base64.b64decode(public.split()[1],validate=True)
    require(len(blob)==51 and blob[:19]==b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20','invalid_public_key')
    return ('from="107.173.191.23",restrict,command="'+COMMAND+'" '+public+'\n').encode()


def safe_file(path,mode):
    st=path.lstat();require(stat.S_ISREG(st.st_mode) and st.st_uid==0 and stat.S_IMODE(st.st_mode)==mode,'unsafe_worker_file')


def install(public):
    line=validate_key(public)
    require(not os.path.lexists(TARGET) and not os.path.lexists(HOME),'existing_worker_path')
    try:pwd.getpwnam('xboard-identity')
    except KeyError:pass
    else:raise ValueError('existing_worker_user')
    result=subprocess.run(['useradd','--system','--user-group','--home-dir',str(HOME),'--no-create-home','--shell','/bin/sh','xboard-identity'],capture_output=True)
    require(result.returncode==0,'worker_user_creation_failed')
    TARGET.mkdir(mode=0o755);HOME.mkdir(mode=0o755);(HOME/'.ssh').mkdir(mode=0o755)
    for name in FILES:
        body=(SOURCE/name).read_bytes()
        with (TARGET/name).open('xb') as out:out.write(body)
        (TARGET/name).chmod(0o644)
    with (HOME/'.ssh/authorized_keys').open('xb') as out:out.write(line)
    (HOME/'.ssh/authorized_keys').chmod(0o644)
    return status(public)


def status(public):
    line=validate_key(public);account=pwd.getpwnam('xboard-identity')
    require(account.pw_uid!=0 and account.pw_dir==str(HOME) and account.pw_shell=='/bin/sh','worker_account_drift')
    for path in (TARGET,HOME,HOME/'.ssh'):
        st=path.lstat();require(stat.S_ISDIR(st.st_mode) and st.st_uid==0 and stat.S_IMODE(st.st_mode)==0o755,'unsafe_worker_directory')
    for name in FILES:safe_file(TARGET/name,0o644)
    safe_file(HOME/'.ssh/authorized_keys',0o644)
    require((HOME/'.ssh/authorized_keys').read_bytes()==line,'worker_authority_drift')
    require(hashes(SOURCE)==hashes(TARGET),'worker_code_drift')
    return {'status':'worker_installed_verified','uid':account.pw_uid,'gid':account.pw_gid,
            'source_hashes':hashes(TARGET),'forced_command':True,'source_address_restricted':True,
            'forwarding_forbidden':True,'relay_service_mutated':False,'pins_stored_on_worker':False}


if __name__=='__main__':
    try:
        p=argparse.ArgumentParser();p.add_argument('operation',choices=['install','status']);a=p.parse_args()
        require(os.geteuid()==0,'root_required');os.umask(0o022)
        raw=sys.stdin.buffer.read(1025);require(len(raw)<=1024,'public_input_too_large')
        public=raw.decode().strip()
        print(json.dumps(globals()[a.operation](public),sort_keys=True))
    except Exception as e:
        code=str(e) if isinstance(e,ValueError) and re.fullmatch('[a-z_]+',str(e)) else type(e).__name__
        print(json.dumps({'status':'failed','reason':code}));raise SystemExit(2)

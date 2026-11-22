#!/usr/bin/env python3
"""Run from the authorized deployment workflow. Never print credentials or SSH output."""
import json, os, sys, time, re
from pathlib import Path
import paramiko
import base64

PINS={
 '107.173.191.23':'AAAAC3NzaC1lZDI1NTE5AAAAIMaqwGqo+a7RFrOqJk84N1s/W0q/9z/JE/12Lu7z0YfC',
 '216.36.108.173':'AAAAC3NzaC1lZDI1NTE5AAAAIN6HqxhKXNatnjJFaeqzK1LADgrVn63i7k0sJXhnLkkv',
 '192.204.56.29':'AAAAC3NzaC1lZDI1NTE5AAAAILj/XzxcNty4PYC/jHgpCPxmtVNtgAwL1iU4h4MPN0ts',
}
class Pin(paramiko.MissingHostKeyPolicy):
 def missing_host_key(self,client,hostname,key):
  if key.get_name()!='ssh-ed25519' or key.get_base64()!=PINS.get(hostname):raise RuntimeError('host_identity_mismatch')
def connect(host,password):
 c=paramiko.SSHClient();c.set_missing_host_key_policy(Pin());c.connect(host,username='root',password=password,look_for_keys=False,allow_agent=False,timeout=20,banner_timeout=20,auth_timeout=20);return c
def execute(client,command):
 _,out,err=client.exec_command(command,timeout=180);data=out.read();error=err.read();code=out.channel.recv_exit_status()
 if code:raise RuntimeError('remote_operation_failed')
 return data
def php(client,code):
 stdin,out,err=client.exec_command('cd /root/Xboard && docker compose exec -T xboard php',timeout=180)
 stdin.write(code);stdin.channel.shutdown_write();data=out.read();err.read()
 if out.channel.recv_exit_status():raise RuntimeError('remote_php_failed')
 return data
PREFIX="<?php require '/www/vendor/autoload.php';$a=require '/www/bootstrap/app.php';$a->make(Illuminate\\Contracts\\Console\\Kernel::class)->bootstrap();\n"
def main():
 operation=sys.argv[1];expected=os.environ['EXPECTED_REVISION']
 enroll_ops=['pair-ingress','register-host','host-command','accept-host','host-status']
 if operation not in enroll_ops+['bootstrap','enable','disable','status','acceptance','verify-allocation','recover-storage']:raise ValueError('invalid_operation')
 origin=connect('107.173.191.23',os.environ['XBOARD_PASSWORD'])
 actual=execute(origin,"cd /root/Xboard && docker inspect --format '{{index .Config.Labels \"org.opencontainers.image.revision\"}}' \"$(docker compose ps -q xboard)\"").decode().strip()
 if actual!=expected:raise RuntimeError('production_revision_mismatch')
 if operation in enroll_ops:
  spec={'action':operation,'address':os.environ.get('PROXY_HOST_ADDRESS',''),'label':os.environ.get('PROXY_HOST_LABEL',''),
        'country':os.environ.get('PROXY_HOST_COUNTRY',''),'recipient':os.environ.get('COMMAND_RECIPIENT','')}
  encoded=base64.b64encode(json.dumps(spec).encode()).decode('ascii')
  result=php(origin,PREFIX+"$input=json_decode(base64_decode('"+encoded+"'),true);\n"+Path(__file__).with_name('manage-enrollment.php').read_text().split('<?php',1)[1])
  print(result.decode());origin.close();return
 if operation=='verify-allocation':
  result=json.loads(php(origin,Path(__file__).with_name('verify-allocation.php').read_text()))
  print(json.dumps(result));origin.close();return
 if operation=='recover-storage':
  print(execute(origin,'df -h /; df -i /; docker system df').decode())
  print(execute(origin,'docker image prune -f --filter label=org.opencontainers.image.source=https://github.com/nanashiwang/Xboard').decode())
  print(execute(origin,'df -h /; df -i /').decode())
  execute(origin,'cd /root/Xboard && docker compose restart xboard')
  origin.close(); return
 if operation=='acceptance':
  from verify_sales import verify
  verify(origin,php,PREFIX,connect,execute)
  return
 for host,secret in [('216.36.108.173','PROXY_US_A_PASSWORD'),('192.204.56.29','PROXY_US_B_PASSWORD')]:
  if operation=='bootstrap':
   node=connect(host,os.environ[secret])
   status=json.loads(execute(origin,'cd /root/Xboard && docker compose exec -T xboard php artisan proxy:inventory status'))
   exists=any(h['address']==host for h in status['hosts'])
   if exists:
    config=json.loads(execute(node,'cat /etc/xboard-proxy-endpoints/agent.json'))
   else:
    target='/tmp/proxy-agent-'+host+'.json'
    execute(origin,'cd /root/Xboard && docker compose exec -T xboard php artisan proxy:inventory init --address='+host+' --output='+target)
    config=json.loads(execute(origin,'cd /root/Xboard && docker compose exec -T xboard cat '+target))
   sftp=node.open_sftp()
   with sftp.open('/etc/xboard-proxy-endpoints/agent.json','w') as f:f.write(json.dumps(config))
   sftp.chmod('/etc/xboard-proxy-endpoints/agent.json',0o600)
   for name in ['agent.py','install-agent.py']:sftp.put(str(Path(__file__).with_name(name)),'/etc/xboard-proxy-endpoints/'+name)
   sftp.close();execute(node,'python3 /etc/xboard-proxy-endpoints/install-agent.py');node.close()
   if not exists:execute(origin,'cd /root/Xboard && docker compose exec -T xboard rm '+target)
   print(host+': authorization agent installed',flush=True)
  elif operation in ['enable','disable']:
   execute(origin,'cd /root/Xboard && docker compose exec -T xboard php artisan proxy:inventory '+operation+' --address='+host)
   print(host+': '+operation,flush=True)
 if operation=='status':
  status=json.loads(execute(origin,'cd /root/Xboard && docker compose exec -T xboard php artisan proxy:inventory status'))
  print(json.dumps(status))
  logs=execute(origin,'cd /root/Xboard && docker compose logs --tail=120 xboard').decode(errors='replace')
  for line in logs.splitlines():
   if any(word in line.lower() for word in ['error','exception','fatal','spawn','exited','listening','started','permission','address already']):
    line=line.split('{"request":')[0]
    line=re.sub(r'https?://\S+|[A-Za-z0-9_+/=-]{40,}', '[redacted]',line)
    print(line[:400])
 origin.close()
if __name__=='__main__':
 try:main()
 except Exception as e:
  safe_codes={'host_identity_mismatch','remote_operation_failed','remote_php_failed','production_revision_mismatch','incomplete_inventory','authentication_not_ready','dual_protocol_egress_failed','wrong_credentials_accepted','expired_authorization_remains','agent_stop_left_authorization_running'}
  reason=str(e) if str(e) in safe_codes else type(e).__name__
  print('operation_failed: '+reason,file=sys.stderr);sys.exit(1)

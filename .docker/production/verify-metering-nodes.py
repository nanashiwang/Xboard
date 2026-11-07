"""Read-only proxy acceptance using the existing internal monitor identity."""
import concurrent.futures,json,os,socket,struct,subprocess,tempfile,time
from pathlib import Path
os.umask(0o077)
binary=Path('/root/Xboard/backups/fleet-20261017/sing-box')
php=r'''require '/www/vendor/autoload.php';
$app=require '/www/bootstrap/app.php';$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
$monitor=App\Models\NodeProbe::findOrFail(1)->user;
if(!$monitor||$monitor->banned||$monitor->u+$monitor->d >= $monitor->transfer_enable||($monitor->expired_at&&$monitor->expired_at<=time()))throw new RuntimeException('Monitor unavailable');
$nodes=App\Models\Server::whereIn('id',[322,323,324,325,354,356,358])->get();
foreach(App\Models\Server::where('show',true)->get() as $node){
 if(in_array('upstream-extension-public',$node->tags??[],true)&&$node->parent?->enabled&&App\Services\ServerService::getAvailableUsers($node->parent)->contains('id',$monitor->id)){$nodes->push($node);break;}
}
$targets=[];
foreach($nodes as $node){
 if(!App\Services\ServerService::getAvailableUsers($node->parent)->contains('id',$monitor->id))throw new RuntimeException('Monitor not authorized');
 $extension=in_array('upstream-extension-public',$node->tags??[],true);
 $row=$node->toArray();$row['port']=(int)$node->port;$row['password']=$node->generateServerPassword($monitor);
 $out=(new App\Services\Probes\ProbeOutbound($monitor->toArray(),[]))->build($row);
 $targets[]=['kind'=>$extension?'extension':'owned','id'=>$node->id,'expected'=>$extension?null:$node->parent->host,'outbound'=>$out];
}echo json_encode($targets,JSON_THROW_ON_ERROR);'''
p=subprocess.run(['docker','compose','exec','-T','xboard','php','-r',php],capture_output=True,text=True,timeout=60)
if p.returncode:raise SystemExit('Monitor query failed; credentials suppressed')
targets=json.loads(p.stdout)
assert len(targets)>=7,'Expected seven retained owned routes'

def receive(sock,n):
 data=b''
 while len(data)<n:
  part=sock.recv(n-len(data))
  if not part:raise OSError('short SOCKS response')
  data+=part
 return data

def udp_dns(port):
 for resolver in ('1.1.1.1','8.8.8.8'):
  try:
   with socket.create_connection(('127.0.0.1',port),timeout=5) as control:
    control.sendall(b'\x05\x01\x00');assert receive(control,2)==b'\x05\x00'
    control.sendall(b'\x05\x03\x00\x01'+b'\0'*6)
    head=receive(control,4);assert head[:2]==b'\x05\x00'
    if head[3]==1:host=socket.inet_ntoa(receive(control,4))
    elif head[3]==3:host=receive(control,receive(control,1)[0]).decode()
    else:raise OSError('unsupported SOCKS relay')
    relay_port=struct.unpack('!H',receive(control,2))[0]
    if host=='0.0.0.0':host='127.0.0.1'
    ident=os.urandom(2)
    query=ident+b'\x01\x00\x00\x01\x00\x00\x00\x00\x00\x00'+b'\x07example\x03com\x00\x00\x01\x00\x01'
    with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as udp:
     udp.settimeout(5);udp.sendto(b'\0\0\0\x01'+socket.inet_aton(resolver)+struct.pack('!H',53)+query,(host,relay_port))
     response=udp.recv(4096);assert response[:3]==b'\0\0\0'
     offset=10 if response[3]==1 else 22 if response[3]==4 else 7+response[4]
     dns=response[offset:]
     if dns[:2]==ident and dns[2]&128 and dns[3]&15==0 and struct.unpack('!H',dns[6:8])[0]>0:return True
  except (OSError,AssertionError,IndexError,struct.error):pass
 return False

def check(item):
    with tempfile.TemporaryDirectory(prefix='owned-fixed-probe-') as directory:
        with socket.socket() as listener:
            listener.bind(('127.0.0.1', 0))
            port = listener.getsockname()[1]
        config = {'log':{'level':'error'}, 'inbounds':[{'type':'socks','tag':'local','listen':'127.0.0.1','listen_port':port}],
                  'outbounds':[item['outbound']], 'route':{'final':'node'}}
        path = Path(directory)/'client.json'; path.write_text(json.dumps(config)); path.chmod(0o600)
        with open(Path(directory)/'core.log','w') as log:
            core = subprocess.Popen([str(binary),'run','-c',str(path)], stdout=log, stderr=log)
            try:
                for _ in range(40):
                    if core.poll() is not None:
                        return {'kind':item['kind'],'id':item['id'],'ok':False,'error':'core_start'}
                    try:
                        with socket.create_connection(('127.0.0.1',port),timeout=.1): break
                    except OSError: time.sleep(.1)
                result = subprocess.run(['curl','--silent','--show-error','--fail','--max-time','12',
                    '--socks5-hostname',f'127.0.0.1:{port}','https://api.ipify.org'],capture_output=True,text=True,timeout=15)
                connected = result.returncode == 0
                ok = (not connected) if item['kind'] in ('unassigned', 'invalid') else connected and (item['expected'] is None or result.stdout.strip()==item['expected'])
                udp_ok = udp_dns(port) if connected else False
                return {'kind':item['kind'],'id':item['id'],'ok':ok and udp_ok,'udp_dns':udp_ok,'connected':connected,
                        'exit_matches':connected and (item['expected'] is None or result.stdout.strip()==item['expected'])}
            finally:
                core.terminate()
                try: core.wait(timeout=3)
                except subprocess.TimeoutExpired: core.kill(); core.wait()

with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(check,targets))
print(json.dumps({'proxy_checks':results,'all_passed':all(r['ok'] for r in results)},indent=2))
assert all(r['ok'] for r in results),'TCP/UDP acceptance failed; compare pre-upgrade baseline'

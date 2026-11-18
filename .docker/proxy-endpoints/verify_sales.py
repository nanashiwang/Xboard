"""Production acceptance with disposable, funded test accounts; no external charge."""
import concurrent.futures, json, os, subprocess, tempfile, time

def check(endpoint, protocol, valid=True):
    credentials=endpoint['credentials']
    # A private curl config keeps credentials out of process command arguments and logs.
    text='silent\nshow-error\nfail\nconnect-timeout = 10\nmax-time = 25\nproxy = "%s://%s:%d"\nproxy-user = "%s:%s"\nurl = "https://api.ipify.org"\n' % (
        'socks5h' if protocol=='SOCKS5' else 'http',endpoint['address'],endpoint['port'],credentials['username'],credentials['password'] if valid else 'invalid-test-password')
    fd,path=tempfile.mkstemp(prefix='proxy-acceptance-');os.chmod(path,0o600)
    try:
        with os.fdopen(fd,'w') as f:f.write(text)
        result=subprocess.run(['curl','--config',path],capture_output=True,timeout=30)
        return result.returncode==0 and result.stdout.decode().strip()==endpoint['address'] if valid else result.returncode!=0
    finally:os.unlink(path)

def verify(origin,php,prefix,connect,execute):
    marker='proxy-acceptance-'+str(int(time.time()))
    # A fail-closed setup transaction: all test seats are reserved before inventory is public.
    code=prefix+r'''$s=app(App\Services\ResidentialProxyService::class);
    $rows=Illuminate\Support\Facades\DB::transaction(function()use($s){
      if(App\Models\ResidentialProxyEndpoint::whereNotNull('user_id')->orWhereNotNull('reserved_order_id')->exists())throw new RuntimeException('Inventory is in use');
      App\Models\ResidentialProxyHost::query()->update(['enabled'=>true]);
      $result=[];
      for($i=0;$i<20;$i++){
        $u=App\Models\User::create(['email'=>'MARKER-'.$i.'@example.invalid','password'=>password_hash(bin2hex(random_bytes(20)),PASSWORD_DEFAULT),'uuid'=>App\Utils\Helper::guid(),'token'=>App\Utils\Helper::guid(),'balance'=>3900]);
        $o=$s->create($u);$s->paid($o,'local-acceptance');
        $result[]=$s->describe(App\Models\ResidentialProxyEndpoint::with('host')->findOrFail($o->proxy_endpoint_id),true);
      }return $result;
    });echo json_encode($rows);'''.replace('MARKER',marker)
    endpoints=[]
    try:
        endpoints=json.loads(php(origin,code))
        if len(endpoints)!=20:raise RuntimeError('incomplete_inventory')
        ids=','.join(str(e['id']) for e in endpoints)
        for attempt in range(15):
            ready=int(php(origin,prefix+"echo App\\Models\\ResidentialProxyEndpoint::whereIn('id',["+ids+"])->whereColumn('revision','applied_revision')->where('running',true)->count();"))
            if ready==20:break
            time.sleep(5)
        if ready!=20:raise RuntimeError('authentication_not_ready')
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            jobs=[pool.submit(check,e,p) for e in endpoints for p in ['HTTP','SOCKS5']]
            results=[j.result() for j in jobs]
        if not all(results):raise RuntimeError('dual_protocol_egress_failed')
        print('20 endpoints / 40 authenticated HTTPS egress checks passed',flush=True)
        for host in ['216.36.108.173','192.204.56.29']:
            e=next(e for e in endpoints if e['address']==host)
            if not all(check(e,p,False) for p in ['HTTP','SOCKS5']):raise RuntimeError('wrong_credentials_accepted')
        # Expire one seat per host. A short real deadline must terminate authorization locally.
        chosen=[next(e for e in endpoints if e['address']==h) for h in ['216.36.108.173','192.204.56.29']]
        chosen_ids=','.join(str(e['id']) for e in chosen)
        php(origin,prefix+"App\\Models\\ResidentialProxyEndpoint::whereIn('id',["+chosen_ids+"])->update(['expires_at'=>time()+25]);")
        time.sleep(50)
        if any(check(e,p) for e in chosen for p in ['HTTP','SOCKS5']):raise RuntimeError('expired_authorization_remains')
        print('Both hosts: expiry denies HTTP and SOCKS5',flush=True)
        # Verify losing the control process also closes every active auth service on each host.
        for host,key in [('216.36.108.173','PROXY_US_A_PASSWORD'),('192.204.56.29','PROXY_US_B_PASSWORD')]:
            node=connect(host,os.environ[key]);execute(node,'systemctl stop xboard-proxy-agent.service')
            try:
                e=next(e for e in endpoints if e['address']==host and e['id'] not in [x['id'] for x in chosen])
                if check(e,'HTTP') or check(e,'SOCKS5'):raise RuntimeError('agent_stop_left_authorization_running')
            finally:execute(node,'systemctl start xboard-proxy-agent.service');node.close()
        print('Agent shutdown closes active authentication on both hosts',flush=True)
    finally:
        # No test grants or funded users remain. Never delete unrelated users or orders.
        cleanup=prefix+r'''Illuminate\Support\Facades\DB::transaction(function(){
          App\Models\ResidentialProxyHost::query()->update(['enabled'=>false]);
          $ids=App\Models\User::where('email','like','MARKER-%@example.invalid')->pluck('id');
          App\Models\ResidentialProxyEndpoint::whereIn('user_id',$ids)->update(['user_id'=>null,'reserved_order_id'=>null,'credentials'=>null,'expires_at'=>null,'revision'=>Illuminate\Support\Facades\DB::raw('revision+1')]);
          App\Models\Order::whereIn('user_id',$ids)->where('product_type','proxy')->delete();
          App\Models\User::whereIn('id',$ids)->delete();
        });'''.replace('MARKER',marker)
        php(origin,cleanup)
        print('Test accounts removed; sales remain disabled pending enable operation',flush=True)

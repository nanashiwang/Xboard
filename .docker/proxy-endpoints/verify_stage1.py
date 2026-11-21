"""Production smoke test. One temporary no-plan buyer, one free port, no external payment."""
import asyncio
import json
import secrets
import subprocess
import sys

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

BOOT = r"""<?php
require '/www/vendor/autoload.php';
$app=require '/www/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
use App\Models\{User,Order,ResidentialProxyEndpoint};
use App\Services\ResidentialProxyService;
use App\Utils\Helper;
use Illuminate\Support\Facades\DB;
$s=app(ResidentialProxyService::class);
"""
CREATE = r"""
DB::transaction(function() use($s,$email) {
    $u=User::create(['email'=>$email,'password'=>password_hash(bin2hex(random_bytes(20)),PASSWORD_DEFAULT),
        'uuid'=>Helper::guid(),'token'=>Helper::guid(),'balance'=>ResidentialProxyService::PRICE]);
    if ($u->fresh()->plan_id) throw new RuntimeException('unexpected ordinary plan');
    $o=$s->create($u);
    if ($o->total_amount || !$s->paid($o,'stage1-smoke-test')) throw new RuntimeException('fixture failed');
    $e=$s->owned($u,$o->proxy_endpoint_id);
    $e->expires_at=time()+300; $e->save();
}); echo 'true';
"""
DETAIL = r"""
$u=User::whereEmail($email)->firstOrFail();
$e=$s->owned($u,Order::whereUserId($u->id)->sole()->proxy_endpoint_id);
echo json_encode($s->describe($e,true));
"""
CLEANUP = r"""
DB::transaction(function() use($email) {
    $u=User::whereEmail($email)->lockForUpdate()->first();
    if (!$u) return;
    ResidentialProxyEndpoint::where('user_id',$u->id)->update(['user_id'=>null,'reserved_order_id'=>null,
        'credentials'=>null,'expires_at'=>null,'revision'=>DB::raw('revision+1')]);
    Order::where('user_id',$u->id)->where('product_type','proxy')->delete();
    $u->delete();
}); echo 'true';
"""


def php(email, code):
    # The SSH command and host pin are supplied by deploy-production.yml. Never
    # send remote exception bodies or issued credentials to the workflow log.
    result = subprocess.run(sys.argv[1:], input=BOOT + f"$email='{email}';\n" + code,
                            capture_output=True, text=True, timeout=25)
    if result.returncode:
        raise RuntimeError("panel test operation failed")
    try:
        return json.loads(result.stdout)
    except ValueError:
        raise RuntimeError("invalid panel test response") from None


async def tunnel(url, reader, writer):
    try:
        async with connect(url, proxy=None, open_timeout=8, close_timeout=1) as ws:
            async def upload():
                while chunk := await reader.read(32768):
                    await ws.send(chunk)

            async def download():
                async for chunk in ws:
                    writer.write(chunk)
                    await writer.drain()

            tasks = [asyncio.create_task(upload()), asyncio.create_task(download())]
            try:
                await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
    except (OSError, TimeoutError, ConnectionClosed):
        pass
    finally:
        writer.close()


async def probe(port, asset, scheme, url, valid=True):
    auth = asset['credentials']
    password = auth['password'] if valid else 'invalid-test-password'
    proc = await asyncio.create_subprocess_exec(
        'curl', '--disable', '--config', '-', '--silent', '--connect-timeout', '8',
        '--max-time', '15', '--noproxy', '', '--proxy', f'{scheme}://127.0.0.1:{port}',
        '--write-out', '\n%{http_code} %{http_connect}', url,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    body, _ = await proc.communicate(f'proxy-user = "{auth["username"]}:{password}"\n'.encode())
    response, _, status = body.rpartition(b'\n')
    if not valid:
        return (status.endswith(b' 407') if scheme == 'http' else proc.returncode == 97)
    if proc.returncode:
        return False
    if url.endswith('/generate_204'):
        return status.startswith(b'204 ')
    return status.startswith(b'200 ') and response.decode().strip() == asset['address']


async def main():
    email = 'stage1-test-' + secrets.token_hex(12) + '@example.invalid'
    server = None
    try:
        php(email, CREATE)
        for _ in range(18):
            asset = php(email, DETAIL)
            if asset['status'] == 'active':
                break
            await asyncio.sleep(4)
        else:
            raise RuntimeError("disposable grant did not become active")
        host = {'216.36.108.173': 'a', '192.204.56.29': 'b'}[asset['address']]
        if asset['port'] not in range(20001, 20011):
            raise RuntimeError("unexpected inventory port")
        url = f"wss://node.lumavia.fyi/residential/v1/{host}/{asset['port']}"
        server = await asyncio.start_server(lambda r, w: tunnel(url, r, w), '127.0.0.1', 0)
        port = server.sockets[0].getsockname()[1]
        for scheme in ['http', 'socks5h']:
            for target in ['https://api.ipify.org', 'https://www.gstatic.com/generate_204']:
                if not await probe(port, asset, scheme, target):
                    raise RuntimeError(f'{scheme} {target} failed')
            if not await probe(port, asset, scheme, 'https://api.ipify.org', False):
                raise RuntimeError(f'{scheme} negative authentication failed')
            print(f'{scheme}: stage one → PX-{asset["id"]} → {asset["address"]}; Google 204; invalid credentials denied', flush=True)
        usage = php(email, r"""$u=User::whereEmail($email)->firstOrFail();
            echo json_encode([$u->plan_id, (int)$u->u + (int)$u->d]);""")
        if usage != [None, 0]:
            raise RuntimeError("unexpected ordinary subscription or traffic")
        print('No ordinary subscription; ordinary traffic counters remain zero', flush=True)
    finally:
        try:
            php(email, CLEANUP)
            print('Removed temporary grant, test order and no-plan account', flush=True)
        except BaseException:
            print('Cleanup requires operator inspection for ' + email, flush=True)
            raise
        finally:
            if server is not None:
                server.close()
                await server.wait_closed()
    # Confirm the node agent has applied the newer revision. Another buyer could
    # acquire the same free port in the interim; check only our revoked identity.
    async with await asyncio.start_server(lambda r, w: tunnel(url, r, w), '127.0.0.1', 0) as server:
        port = server.sockets[0].getsockname()[1]
        await asyncio.sleep(45)
        for scheme in ['http', 'socks5h']:
            if await probe(port, asset, scheme, 'https://api.ipify.org'):
                raise RuntimeError('removed test grant still works')
    print('Removed credentials cannot reach the IP probe through either protocol', flush=True)


if __name__ == '__main__':
    asyncio.run(main())

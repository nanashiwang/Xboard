<?php
namespace App\Services;

use App\Exceptions\ApiException;
use App\Models\{Order,Plan,User,ResidentialProxyHost,ResidentialProxyEndpoint};
use App\Utils\Helper;
use Carbon\Carbon;
use Illuminate\Support\Facades\DB;

class ResidentialProxyService
{
    public const PRICE = 3900;
    public const LEASE_SECONDS = 120;

    private function lockPlan(): Plan {
        // First statement must acquire a write lock: SQLite ignores SELECT FOR UPDATE.
        Plan::where('is_proxy',true)->increment('allocation_version');
        $plan = Plan::where('is_proxy',true)->lockForUpdate()->first();
        if (!$plan) throw new ApiException('代理商品暂未开放');
        return $plan;
    }

    public function create(User $buyer, ?int $endpointId = null): Order {
        return DB::transaction(function() use ($buyer,$endpointId) {
            $plan=$this->lockPlan();
            $user=User::lockForUpdate()->findOrFail($buyer->id);
            if ($user->banned) throw new ApiException('账号不可购买');
            if (app(UserService::class)->isNotCompleteOrderByUserId($user->id)) throw new ApiException('请先处理未完成订单');
            $query=ResidentialProxyEndpoint::whereHas('host',fn($q)=>$q->where('enabled',true)->where('seen_at','>=',time()-60));
            if ($endpointId) {
                $query->where('user_id', $user->id)->whereKey($endpointId);
            } else {
                // Host addresses are unique. A retained (expired) port still belongs to its buyer.
                $ownedOnHost = DB::table('residential_proxy_endpoints as owned')
                    ->selectRaw('COUNT(*)')
                    ->where('owned.user_id', $user->id)
                    ->whereColumn('owned.host_id', 'residential_proxy_endpoints.host_id');
                $query->whereNull('user_id')->whereNull('reserved_order_id')
                    ->orderBy($ownedOnHost)->orderBy('id');
            }
            $endpoint = $query->lockForUpdate()->first();
            if (!$endpoint || $endpoint->reserved_order_id) throw new ApiException('代理暂无可用库存，或该代理暂不可续费');
            $balance=min(max(0,(int)$user->balance),self::PRICE);
            $order=Order::create(['user_id'=>$user->id,'plan_id'=>$plan->id,'product_type'=>'proxy',
                'proxy_endpoint_id'=>$endpoint->id,'period'=>'monthly','trade_no'=>Helper::generateOrderNo(),
                'total_amount'=>self::PRICE-$balance,'balance_amount'=>$balance,'status'=>Order::STATUS_PENDING,
                'type'=>$endpointId?Order::TYPE_RENEWAL:Order::TYPE_NEW_PURCHASE]);
            $user->balance-=$balance; $user->save();
            $endpoint->reserved_order_id=$order->id; $endpoint->save();
            return $order;
        },5);
    }

    public function paid(Order $input,string $callback): bool {
        return DB::transaction(function() use($input,$callback) {
            $this->lockPlan();
            $order=Order::lockForUpdate()->findOrFail($input->id);
            if ($order->status===Order::STATUS_COMPLETED) return true;
            // A delayed payment for a cancelled order must never steal a reallocated port.
            if ($order->status===Order::STATUS_CANCELLED) {
                if (!$order->paid_at) {
                    $user=User::lockForUpdate()->findOrFail($order->user_id);
                    $user->balance+=(int)$order->total_amount+(int)$order->handling_amount; $user->save();
                    $order->paid_at=time(); $order->callback_no=$callback; $order->save();
                }
                return true;
            }
            if (!in_array($order->status,[Order::STATUS_PENDING,Order::STATUS_PROCESSING],true)) return false;
            $endpoint=ResidentialProxyEndpoint::lockForUpdate()->findOrFail($order->proxy_endpoint_id);
            if ($endpoint->reserved_order_id !== $order->id || ($endpoint->user_id && $endpoint->user_id !== $order->user_id)) throw new \RuntimeException('Proxy reservation mismatch');
            if (!$endpoint->user_id) {
                $endpoint->user_id=$order->user_id;
                $endpoint->credentials=$this->newCredentials();
            }
            $endpoint->expires_at=Carbon::createFromTimestamp(max(time(),(int)$endpoint->expires_at))->addMonthNoOverflow()->timestamp;
            $endpoint->reserved_order_id=null; $endpoint->revision++; $endpoint->save();
            $order->status=Order::STATUS_COMPLETED; $order->paid_at=$order->paid_at?:time(); $order->callback_no=$callback; $order->save();
            return true;
        },5);
    }

    public function cancel(Order $input): bool {
        return DB::transaction(function() use($input) {
            $this->lockPlan(); $order=Order::lockForUpdate()->findOrFail($input->id);
            if ($order->status===Order::STATUS_CANCELLED) return true;
            if ($order->status!==Order::STATUS_PENDING) return false;
            $user=User::lockForUpdate()->findOrFail($order->user_id);
            $user->balance+=(int)$order->balance_amount; $user->save();
            ResidentialProxyEndpoint::where('reserved_order_id',$order->id)->update(['reserved_order_id'=>null]);
            $order->status=Order::STATUS_CANCELLED; $order->save(); return true;
        },5);
    }

    public function newCredentials(): array {
        return ['username'=>'cp_'.bin2hex(random_bytes(8)),'password'=>bin2hex(random_bytes(18))];
    }

    public function owned(User $user,int $id): ResidentialProxyEndpoint {
        if ($user->banned) throw new ApiException('账号已停用',403);
        return ResidentialProxyEndpoint::with('host')->where('user_id',$user->id)->findOrFail($id);
    }

    public function describe(ResidentialProxyEndpoint $e,bool $secrets=false): array {
        $active=$e->expires_at>time();
        $ready=$active && $e->host->enabled && $e->checked_at>=time()-60 && $e->running && $e->revision===$e->applied_revision;
        $data=['id'=>$e->id,'name'=>$e->name,'address'=>$e->host->address,'port'=>$e->port,'country'=>'美国',
            'protocols'=>['SOCKS5','HTTP'],'speed_mbps'=>100,'unlimited_traffic'=>true,'price'=>self::PRICE,
            'expires_at'=>$e->expires_at,'status'=>!$active?'expired':($ready?'active':'provisioning'),
            'checked_at'=>$e->checked_at,'revision'=>$e->revision];
        if ($secrets && $active) $data['credentials']=$e->credentials;
        return $data;
    }

    public function index(User $user): array {
        if ($user->banned) throw new ApiException('账号已停用',403);
        return ['price'=>self::PRICE,'available'=>ResidentialProxyEndpoint::whereNull('user_id')->whereNull('reserved_order_id')
            ->whereHas('host',fn($q)=>$q->where('enabled',true)->where('seen_at','>=',time()-60))->count(),
            'items'=>ResidentialProxyEndpoint::with('host')->where('user_id',$user->id)->orderByDesc('id')->get()->map(fn($e)=>$this->describe($e))->all(),
            'pending'=>Order::where('user_id',$user->id)->where('product_type','proxy')->whereIn('status',[0,1])->latest('id')->first(['trade_no','status','total_amount','balance_amount']),
        ];
    }

    public function update(User $user,int $id,array $data): array {
        return DB::transaction(function() use($user,$id,$data) {
            $this->lockPlan(); $e=$this->owned($user,$id);
            if (isset($data['name'])) $e->name=$data['name'];
            if (!empty($data['reset'])) { if ($e->expires_at<=time()) throw new ApiException('到期代理请先续费'); $e->credentials=$this->newCredentials(); $e->revision++; }
            $e->save(); return $this->describe($e,true);
        },5);
    }

    public function snapshot(ResidentialProxyHost $host): array {
        $now=time();
        return ['server_time'=>$now,'lease_until'=>$now+self::LEASE_SECONDS,'address'=>$host->address,
            'endpoints'=>ResidentialProxyEndpoint::where('host_id',$host->id)->orderBy('port')->get()->map(function($e) use($host,$now) {
                $user=$e->user_id?User::find($e->user_id):null;
                $enabled=$host->enabled && $user && !$user->banned && $e->expires_at>$now;
                return ['id'=>$e->id,'port'=>$e->port,'revision'=>$e->revision,'enabled'=>(bool)$enabled,
                    'expires_at'=>$enabled?$e->expires_at:0,'credentials'=>$enabled?$e->credentials:null];
            })->all()];
    }
}

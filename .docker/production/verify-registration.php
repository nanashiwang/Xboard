<?php
// Non-delivery probes: every POST must be rejected before mail/account writes.
require '/www/vendor/autoload.php';
$app = require '/www/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
use Illuminate\Support\Facades\Http;
use App\Models\{User, MailLog};

function ensure($condition, $message) { if (!$condition) throw new RuntimeException($message); }
ensure((bool) admin_setting('captcha_enable') && admin_setting('captcha_type') === 'turnstile', 'Turnstile must already be enabled');
ensure((bool) admin_setting('register_limit_by_ip_enable') && app(App\Services\Auth\RegistrationGuard::class)->enabled(), 'Registration policy not enabled');
$prefix = 'guard-proof-' . bin2hex(random_bytes(8)); $emails = []; $results = [];
foreach (['capybarago.uk', 'taige.us', 'board.taige.us'] as $index => $host) {
    $config = Http::withOptions(['force_ip_resolve' => 'v4'])->connectTimeout(5)->timeout(15)->get('https://' . $host . '/api/v1/guest/comm/config');
    ensure($config->successful() && (int) $config->json('data.is_captcha') === 1 && $config->json('data.captcha_type') === 'turnstile', 'Public captcha config mismatch');
    foreach (['auth/register', 'comm/sendEmailVerify'] as $operation) {
        $email = $prefix . '-' . count($emails) . '@fldubai.com'; $emails[] = $email;
        $response = Http::withOptions(['force_ip_resolve' => 'v4'])->connectTimeout(5)->timeout(15)->post('https://' . $host . '/api/v1/passport/' . $operation, ['email'=>$email,'password'=>'never-created-random-test']);
        ensure($response->status()===403 && str_contains($response->json('message') ?? '', '此邮箱'), 'Blocked-domain rejection mismatch');
        $results[]=['host'=>$host,'operation'=>$operation,'status'=>$response->status(),'reason'=>'email_domain'];
    }
}
// All hosts must share the real origin source-IP bucket. Three blocked sends
// already consumed three slots; missing-token sends consume slots four and five.
foreach ([400,400,429] as $expected) {
    $email=$prefix.'-'.count($emails).'@example.invalid';$emails[]=$email;
    $response=Http::withOptions(['force_ip_resolve' => 'v4'])->connectTimeout(5)->timeout(15)->post('https://capybarago.uk/api/v1/passport/comm/sendEmailVerify',['email'=>$email]);
    ensure($response->status()===$expected,'Cross-host quota or missing-token rejection mismatch');
    $results[]=['host'=>'capybarago.uk','operation'=>'comm/sendEmailVerify','status'=>$response->status()];
}
ensure(User::whereIn('email',$emails)->count()===0,'Probe unexpectedly created an account');
ensure(MailLog::whereIn('email',$emails)->count()===0,'Probe unexpectedly dispatched mail');
$guard=app(App\Services\Auth\RegistrationGuard::class);
$hashes=array_map(fn($email)=>$guard->key('email',$email),$emails);$events=[];
foreach (glob(storage_path('logs/registration-*.log')) as $path) {
    $handle=fopen($path,'r');
    while (($line=fgets($handle))!==false) {
        $position=strpos($line,'registration_event ');if($position===false)continue;
        $json=trim(substr($line,$position+strlen('registration_event ')));
        // Monolog's line formatter appends the empty extra context as " []".
        $context=json_decode(preg_replace('/\s+\[\]\s*$/','',$json),true);
        if (!is_array($context)||!in_array($context['email_hash']??'', $hashes,true))continue;
        ensure(!str_contains(json_encode($context),'@'),'Audit exposes full email');
        $events[]=['operation'=>$context['operation'],'status'=>$context['status'],'reason'=>$context['reason'],'request_id_present'=>!empty($context['request_id'])];
    }
    fclose($handle);
}
ensure(count($events)===count($results),'Audit events missing or duplicated');
echo json_encode(['public_probes'=>$results,'audit_events'=>$events,'accounts_created'=>0,'mail_dispatched'=>0,'snapshot_persistent'=>is_file(storage_path('logs/security-backups/registration-20261103.json'))],JSON_PRETTY_PRINT|JSON_UNESCAPED_SLASHES).PHP_EOL;

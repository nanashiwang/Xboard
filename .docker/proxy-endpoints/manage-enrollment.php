<?php
use App\Models\ResidentialProxyHost;
use App\Services\ResidentialEnrollment;
use Illuminate\Support\Facades\Validator;

$action = $input['action'];
$service = app(ResidentialEnrollment::class);
if (in_array($action, ['pair-ingress','register-host','host-command'], true)) {
    Validator::make($input, ['recipient'=>'required|regex:/^[0-9a-f]{64}$/D'])->validate();
    $public = hex2bin($input['recipient']);
    // Test the recipient before any database change (also rejects low-order keys).
    sodium_crypto_box_seal('check', $public);
}
if ($action === 'pair-ingress') {
    $result = ['command'=>ResidentialEnrollment::installCommand('ingress', ResidentialEnrollment::ingressToken())];
} elseif ($action === 'register-host') {
    $data = Validator::make($input, ['address'=>'required|ipv4','label'=>'required|string|max:80','country'=>'required|string|max:40'])->validate();
    $result = $service->register($data);
} else {
    $host = ResidentialProxyHost::whereNotNull('enrollment_state')->where('address', $input['address'])->firstOrFail();
    if ($action === 'host-command') {
        $result = $service->issue($host->id);
    } elseif ($action === 'accept-host') {
        $service->start($host->id);
        echo 'Acceptance requested'; return;
    } elseif ($action === 'host-status') {
        echo json_encode($host->only(['id','address','label','country','enabled','enrollment_state','probe_error','seen_at'])); return;
    } else {
        throw new InvalidArgumentException('Unknown enrollment action');
    }
}
echo 'sealed_command=' . bin2hex(sodium_crypto_box_seal(json_encode($result, JSON_THROW_ON_ERROR), $public));

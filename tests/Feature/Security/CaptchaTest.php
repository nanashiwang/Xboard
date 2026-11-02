<?php
namespace Tests\Feature\Security;

use App\Services\CaptchaService;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\{Cache, Http};
use Tests\TestCase;

class CaptchaTest extends TestCase
{
    use RefreshDatabase;
    protected function setUp(): void
    {
        parent::setUp(); Cache::flush(); Http::preventStrayRequests();
        admin_setting(['captcha_enable'=>1,'captcha_type'=>'turnstile','turnstile_secret_key'=>'test-secret','turnstile_allowed_hostnames'=>['capybarago.uk'],'turnstile_action'=>'passport']);
    }
    private function verify(mixed $token='test-token'): array
    {
        return app(CaptchaService::class)->verify(Request::create('https://capybarago.uk/api/v1/passport/auth/register','POST',['turnstile_token'=>$token]));
    }
    public function test_token_requires_server_confirmation_hostname_and_action(): void
    {
        Http::fakeSequence()->push(['success'=>false])
            ->push(['success'=>true,'hostname'=>'evil.test','action'=>'passport'])
            ->push(['success'=>true,'hostname'=>'capybarago.uk','action'=>'other'])
            ->push(['success'=>true,'hostname'=>'capybarago.uk','action'=>'passport']);
        for ($i=0; $i<3; $i++) $this->assertFalse($this->verify()[0]);
        $this->assertTrue($this->verify()[0]);
        Http::assertSent(fn($r)=>$r['secret']==='test-secret' && $r['response']==='test-token');
    }
    public function test_missing_malformed_or_oversized_token_never_contacts_provider(): void
    {
        Http::fake();
        foreach (['',null,['bad'],str_repeat('a',2049)] as $token) $this->assertFalse($this->verify($token)[0]);
        Http::assertNothingSent();
    }
    public function test_expired_replayed_token_and_provider_failure_fail_closed(): void
    {
        Http::fakeSequence()->push(['success'=>true,'hostname'=>'capybarago.uk','action'=>'passport'])
            ->push(['success'=>false,'error-codes'=>['timeout-or-duplicate']])->push('not json',200)->push([],503);
        $this->assertTrue($this->verify()[0]); $this->assertFalse($this->verify()[0]);
        $this->assertSame(503,$this->verify()[1][0]); $this->assertSame(503,$this->verify()[1][0]);
    }
    public function test_network_failure_is_bounded_and_does_not_expose_secrets(): void
    {
        Http::fake(fn()=>throw new \Illuminate\Http\Client\ConnectionException('test-secret sensitive transport error'));
        $result=$this->verify(); $this->assertSame(503,$result[1][0]); $this->assertStringNotContainsString('test-secret',json_encode($result));
    }
}

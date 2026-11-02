<?php
namespace Tests\Feature\Security;

use App\Models\Setting;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\{Cache, File, Log, Validator};
use Tests\TestCase;

class RegistrationPolicyTest extends TestCase
{
    use RefreshDatabase;
    public function test_config_bounds_and_no_unknown_hostnames(): void
    {
        $rules=\App\Http\Requests\Admin\ConfigSave::RULES;
        $this->assertTrue(Validator::make(['register_limit_count'=>3,'register_limit_daily_count'=>10,'turnstile_allowed_hostnames'=>['capybarago.uk'],'registration_blocked_email_domains'=>['fldubai.com']],$rules)->passes());
        foreach ([['register_limit_count'=>0],['register_limit_expire'=>1441],['turnstile_allowed_hostnames'=>['attacker.invalid']],['registration_blocked_email_domains'=>['*']]] as $bad) $this->assertTrue(Validator::make($bad,$rules)->fails());
    }
    public function test_audit_channel_does_not_corrupt_default_stack(): void
    {
        $this->assertSame(['daily'],config('logging.channels.stack.channels'));
        $this->assertSame(7,config('logging.channels.registration.days'));
        Log::channel('stack')->info('registration_test_stack');
    }
    public function test_apply_and_guarded_rollback_preserve_other_settings(): void
    {
        if (getenv('GUARD_CONCURRENCY_STORE')!=='redis') $this->markTestSkipped('Isolated Redis required for production-policy command regression');
        $directory=sys_get_temp_dir().'/guard-policy-'.bin2hex(random_bytes(8));
        $original=storage_path(); $this->app->useStoragePath($directory);
        config(['cache.prefix'=>'guard-policy-'.bin2hex(random_bytes(8))]); Cache::purge('redis');Cache::setDefaultDriver('redis');
        try {
            admin_setting(['captcha_enable'=>0,'email_verify'=>1,'turnstile_secret_key'=>'not-a-real-key','turnstile_site_key'=>'not-a-real-sitekey','unrelated'=>'preserved']);
            $this->artisan('security:registration apply')->assertSuccessful();
            $this->assertSame(1,(int)admin_setting('captcha_enable'));
            $path=storage_path('app/security-backups/registration-20261103.json');
            $this->assertSame(0600,fileperms($path)&0777);
            $this->assertStringNotContainsString('not-a-real-key',file_get_contents($path));
            $this->artisan('security:registration apply')->assertSuccessful();
            admin_setting(['register_limit_count'=>4]);
            $this->artisan('security:registration rollback')->assertFailed();
            admin_setting(['register_limit_count'=>3]);
            $this->artisan('security:registration rollback')->assertSuccessful();
            $this->assertSame(0,(int)admin_setting('captcha_enable'));
            $this->assertSame('preserved',admin_setting('unrelated'));
            $this->assertFalse(Setting::where('name','registration_guard_enable')->exists());
        } finally {Cache::setDefaultDriver('array');$this->app->useStoragePath($original);File::deleteDirectory($directory);}
    }
}

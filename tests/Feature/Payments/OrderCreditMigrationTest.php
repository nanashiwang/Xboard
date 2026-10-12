<?php

namespace Tests\Feature\Payments;

use App\Models\Order;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;
use Tests\TestCase;

class OrderCreditMigrationTest extends TestCase
{
    use RefreshDatabase;

    public function test_legacy_credit_is_preserved_when_migrating_and_rolling_back(): void
    {
        $migration = require database_path('migrations/2026_05_30_000000_rename_refund_amount_to_surplus_credit.php');
        $migration->down();
        $id = DB::table('v2_order')->insertGetId([
            'user_id' => 1, 'plan_id' => 1, 'type' => Order::TYPE_UPGRADE,
            'period' => 'monthly', 'trade_no' => 'legacy-credit', 'total_amount' => 0,
            'refund_amount' => 989, 'created_at' => time(), 'updated_at' => time(),
        ]);
        $migration->up();
        $this->assertFalse(Schema::hasColumn('v2_order', 'refund_amount'));
        $this->assertEquals(989, Order::findOrFail($id)->surplus_credit);
        $migration->down();
        $this->assertEquals(989, DB::table('v2_order')->where('id', $id)->value('refund_amount'));
        $migration->up();
    }

    public function test_previously_migrated_database_does_not_repeat_the_column_rename(): void
    {
        $this->assertTrue(Schema::hasColumn('v2_order', 'surplus_credit'));
        $this->assertDatabaseHas('migrations', [
            'migration' => '2026_05_30_000000_rename_refund_amount_to_surplus_credit',
        ]);
        $this->artisan('migrate', ['--force' => true])->assertExitCode(0);
        $this->assertFalse(Schema::hasColumn('v2_order', 'refund_amount'));
        $this->assertTrue(Schema::hasColumn('v2_order', 'surplus_credit'));
    }
}

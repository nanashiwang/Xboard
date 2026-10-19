<?php

namespace Tests\Feature\Operations;

use App\Http\Controllers\V2\Admin\SystemController;
use Illuminate\Http\Request;
use Laravel\Horizon\Contracts\JobRepository;
use Mockery;
use Tests\TestCase;

class FailedJobPaginationTest extends TestCase
{
    private function page(int $current, int $pageSize, int $total): array
    {
        $repository = Mockery::mock(JobRepository::class);
        $offset = ($current - 1) * min(100, $pageSize);
        for ($start = $offset; $start < $offset + min(100, $pageSize); $start += 50) {
            $count = max(0, min(50, $total - $start));
            $jobs = collect();
            for ($i = 0; $i < $count; $i++) {
                $jobs->push((object) ['id' => 'job-' . ($start + $i), 'failed_at' => 10000 - $start - $i]);
            }
            $repository->shouldReceive('getFailed')->once()->with($start - 1)->andReturn($jobs);
            if ($count < 50) break;
        }
        $repository->shouldReceive('countFailed')->once()->andReturn($total);
        return app(SystemController::class)->getHorizonFailedJobs(
            Request::create('/', 'GET', ['current' => $current, 'page_size' => $pageSize]),
            $repository
        )->getData(true);
    }

    public function test_page_after_the_first_fifty_jobs_is_read_from_horizon(): void
    {
        $page = $this->page(7, 10, 798);
        $this->assertCount(10, $page['data']);
        $this->assertSame('job-60', $page['data'][0]['id']);
        $this->assertSame('job-69', $page['data'][9]['id']);
        $this->assertSame(798, $page['total']);
    }

    public function test_one_hundred_job_page_reads_two_chunks(): void
    {
        $page = $this->page(2, 100, 798);
        $this->assertCount(100, $page['data']);
        $this->assertSame('job-100', $page['data'][0]['id']);
        $this->assertSame('job-199', $page['data'][99]['id']);
    }

    public function test_last_page_and_empty_page_keep_the_total(): void
    {
        $page = $this->page(80, 10, 798);
        $this->assertCount(8, $page['data']);
        $this->assertSame('job-797', $page['data'][7]['id']);
        $this->assertSame([], $this->page(81, 10, 798)['data']);
    }

    public function test_page_size_is_bounded(): void
    {
        $page = $this->page(1, 10000, 798);
        $this->assertCount(100, $page['data']);
        $this->assertSame(100, $page['page_size']);
    }
}

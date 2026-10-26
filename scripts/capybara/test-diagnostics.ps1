#requires -Version 5.1
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'diagnose-windows.ps1') -OutputPath 'unused.json'
$script:passed = 0
function Assert($Condition, [string]$Message) {
    if (-not $Condition) { throw $Message }
    $script:passed++
}
function Assert-Throws([scriptblock]$Operation, [string]$Message) {
    $caught = $false
    try { & $Operation | Out-Null } catch { $caught = $true }
    Assert $caught $Message
}
$fixtureSecret = 'test-secret-never-export-123456'
$fixture = @"
external-controller: 127.0.0.1:1
mixed-port: 12345
secret: $fixtureSecret
proxies:
- name: 美国01｜2×｜家宽
  type: vless
  server: entry.example
  port: 443
  uuid: uuid-private-canary
  ws-opts:
    path: /private-path-canary
- name: '日本01｜1×'
  server: japan.example
  port: 443
proxy-groups:
- name: GROUP
  type: select
"@
$config = Get-LocalConfig $fixture
Assert ($config.Base -eq 'http://127.0.0.1:1' -and $config.Port -eq 12345 -and $config.Secret -eq $fixtureSecret) 'Config scalar parsing'
foreach ($invalid in @('localhost:80','127.0.0.1.evil:80','example.com:80','127.0.0.1:0','127.0.0.1:65536','user@127.0.0.1:80')) {
    $bad = $fixture.Replace('127.0.0.1:1', $invalid)
    Assert-Throws { Get-LocalConfig $bad } ('Reject controller ' + $invalid)
}
Assert-Throws { Get-LocalConfig ($fixture.Replace('mixed-port: 12345','mixed-port: 99999')) } 'Reject invalid mixed port'
Assert ((Get-Scalar "secret: 'abc''def'" 'secret') -eq "abc'def") 'YAML single quoted scalar'
Assert ((Get-Scalar 'name: "hello world"' 'name') -eq 'hello world') 'YAML double quoted scalar'
Assert ((Get-NodeEndpoint $fixture '美国01｜2×｜家宽').Host -eq 'entry.example') 'Selected node endpoint'
Assert ((Get-NodeEndpoint $fixture '日本01｜1×').Host -eq 'japan.example') 'Quoted node endpoint'
Assert ($null -eq (Get-NodeEndpoint $fixture 'missing')) 'Absent node endpoint'
Assert ((Get-FailureClass 'x509: certificate signed by unknown authority uuid-private-canary') -eq 'tls_certificate') 'TLS error classification'
Assert ((Get-FailureClass 'lookup private.example: no such host') -eq 'dns_resolution') 'DNS error classification'
Assert ((Get-FailureClass 'connectex: forbidden by its access permissions (10013)') -eq 'socket_access_denied') 'Windows access denial'
Assert ((Get-FailureClass 'private-path-canary') -eq 'other') 'No raw text fallback'
Assert-Throws { Invoke-Probe 'https://example.com' -Secret $fixtureSecret } 'No auth to remote endpoint'

$temp = Join-Path ([IO.Path]::GetTempPath()) ('capybara-diagnostic-tests-' + [guid]::NewGuid())
[IO.Directory]::CreateDirectory($temp) | Out-Null
$server = $null
try {
    $portFile = Join-Path $temp 'port.txt'
    $python = (Get-Command python3 -ErrorAction SilentlyContinue)
    if (-not $python) { $python = Get-Command python }
    $start = [Diagnostics.ProcessStartInfo]::new()
    $start.FileName = $python.Source
    $start.Arguments = '"' + (Join-Path $PSScriptRoot 'test-http-fixture.py') + '" "' + $portFile + '"'
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $server = [Diagnostics.Process]::Start($start)
    $deadline = [DateTime]::UtcNow.AddSeconds(8)
    while (-not (Test-Path $portFile) -and [DateTime]::UtcNow -lt $deadline) { Start-Sleep -Milliseconds 100 }
    Assert (Test-Path $portFile) 'HTTP fixture started'
    $port = [int]([IO.File]::ReadAllText($portFile))
    $base = 'http://127.0.0.1:' + $port
    $probe = Invoke-Probe ($base + '/ok') -Secret $fixtureSecret -ReadJson
    Assert ($probe.http_status -eq 200 -and $probe.Data.authorized) 'Authenticated loopback GET'
    $redirect = Invoke-Probe ($base + '/redirect') -Secret $fixtureSecret -ReadJson
    Assert ($redirect.http_status -eq 302 -and -not $redirect.Data) 'Do not follow redirects'
    Assert ((Invoke-Probe ($base + '/timeout') -TimeoutSeconds 1).failure -eq 'timeout') 'Bound network wait'
    $tcp = Get-TcpStatus '127.0.0.1' $port
    Assert ($tcp -is [string] -and $tcp -eq 'connected') 'Check TCP listener without leaked Task values'
    $ws = [Net.WebSockets.ClientWebSocket]::new()
    $ws.Options.Proxy = $null
    try {
        [void]$ws.ConnectAsync([uri]($base.Replace('http://','ws://') + '/logs?level=warning'), [Threading.CancellationToken]::None).GetAwaiter().GetResult()
        $classes = Get-CoreLogClasses $ws
        Assert ($classes.tls_certificate -eq 1 -and $classes.dns_resolution -eq 1 -and $classes.Count -eq 2) 'Redact real streamed core logs to categories'
    } finally { $ws.Dispose() }
    Assert ((Invoke-Probe ($base + '/body-timeout') -TimeoutSeconds 1 -ReadJson).failure -eq 'timeout') 'Bound body buffering'

    # Exercise the whole reporting path with source objects containing credential canaries.
    function Invoke-Probe([string]$Url, [int]$TimeoutSeconds=8, [string]$Secret, [string]$ProxyUrl, [switch]$ReadJson) {
        $data = $null
        if ($Url.EndsWith('/version')) { $data = [pscustomobject]@{ version='test-core'; secret=$fixtureSecret } }
        if ($Url.EndsWith('/configs')) { $data = [pscustomobject]@{ mode='rule'; secret=$fixtureSecret } }
        if ($Url.EndsWith('/proxies')) {
            $data = [pscustomobject]@{ proxies=[pscustomobject]@{ '美国01｜2×｜家宽'=[pscustomobject]@{type='Vless'; uuid='uuid-private-canary'}; GROUP=[pscustomobject]@{type='Selector'; now='美国01｜2×｜家宽'} } }
        }
        if ($Url.Contains('/delay?')) { $data = [pscustomobject]@{ delay=123; private='private-path-canary' } }
        return @{ http_status=200; elapsed_ms=5; Data=$data }
    }
    function Get-TcpStatus([string]$Server, [int]$Port) { return 'connected' }
    $RuntimePath = Join-Path $temp 'runtime.yaml'
    [IO.File]::WriteAllText($RuntimePath,$fixture,[Text.UTF8Encoding]::new($false))
    $NodeMatch = '美国01'
    $report = Invoke-CapybaraDiagnostic
    $serialized = $report | ConvertTo-Json -Depth 12
    Assert ($report -is [System.Collections.IDictionary] -and $report.stage -eq 'completed' -and $report.node_tests.Count -eq 3) 'Full report completed'
    Assert ($serialized -notmatch 'test-secret-never-export|uuid-private-canary|private-path-canary|runtime.yaml') 'Report redacts source credentials and paths'
    Assert ($report.node_tests[0].delay_ms -eq 123 -and $report.selected_groups.Count -eq 1) 'Keep useful probe and selection evidence'
} finally {
    if ($server -and -not $server.HasExited) { $server.Kill(); $server.WaitForExit() }
    Remove-Item -LiteralPath $temp -Recurse -Force
}
Write-Host ('Passed ' + $script:passed + ' diagnostic checks')

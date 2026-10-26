#requires -Version 5.1
param(
    [string]$NodeMatch = '美国01',
    [string]$RuntimePath,
    [string]$OutputPath = (Join-Path ([Environment]::GetFolderPath('Desktop')) ('Capybara-diagnostic-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '.json'))
)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Net.Http

function Get-FailureClass([string]$Text) {
    # Never return raw exception or log text: it may include URLs, UUIDs or WS paths.
    if ($Text -match '(?i)x509|certificate|certificat|trust failure|remote public key|证书') { return 'tls_certificate' }
    if ($Text -match '(?i)no such host|name resolution|resolve|dns|找不到.*主机|未知.*主机') { return 'dns_resolution' }
    if ($Text -match '(?i)forbidden.*permissions|access.*denied|WSAEACCES|10013|权限.*禁止') { return 'socket_access_denied' }
    if ($Text -match '(?i)refused|10061|拒绝') { return 'connection_refused' }
    if ($Text -match '(?i)reset|10054|重置') { return 'connection_reset' }
    if ($Text -match '(?i)tls|ssl|handshake') { return 'tls_handshake' }
    if ($Text -match '(?i)timeout|timed out|canceled|cancelled|超时|取消') { return 'timeout' }
    if ($Text -match '(?i)network.*unreachable|no route|10051|无法访问.*网络') { return 'network_unreachable' }
    if ($Text -match '(?i)unexpected EOF|end of stream') { return 'unexpected_eof' }
    return 'other'
}

function Get-Scalar([string]$Text, [string]$Key) {
    $match = [regex]::Match($Text, '(?m)^\s*' + [regex]::Escape($Key) + ':\s*([^\r\n]+)\r?$')
    if (-not $match.Success) { return $null }
    $value = $match.Groups[1].Value.Trim()
    if ($value.StartsWith('"')) { return ($value | ConvertFrom-Json) }
    if ($value.StartsWith("'") -and $value.EndsWith("'")) { return $value.Substring(1, $value.Length - 2).Replace("''", "'") }
    return $value
}

function Get-LocalConfig([string]$Text) {
    $controller = Get-Scalar $Text 'external-controller'
    if ($controller -notmatch '^127\.0\.0\.1:([0-9]{1,5})$') { throw 'Controller must use 127.0.0.1' }
    $apiPort = [int]$Matches[1]
    $mixed = 0
    if (-not [int]::TryParse((Get-Scalar $Text 'mixed-port'), [ref]$mixed) -or $mixed -lt 1 -or $mixed -gt 65535 -or $apiPort -lt 1 -or $apiPort -gt 65535) { throw 'Invalid local port' }
    $secret = Get-Scalar $Text 'secret'
    if ($secret -notmatch '^[A-Za-z0-9-]{16,128}$') { throw 'Invalid local controller authentication' }
    return @{ Base = 'http://' + $controller; Secret = $secret; Port = $mixed }
}

function Get-NodeEndpoint([string]$Text, [string]$Name) {
    $section = [regex]::Match($Text, '(?ms)^proxies:\s*\r?\n(.*?)(?=^[A-Za-z][A-Za-z0-9_-]*:|\z)')
    foreach ($block in [regex]::Split($section.Groups[1].Value, '(?m)^\s*- (?=[A-Za-z])')) {
        if ((Get-Scalar $block 'name') -eq $Name) {
            $server = Get-Scalar $block 'server'
            $nodePort = 0
            if ($server -notmatch '^[A-Za-z0-9.-]+$' -or -not [int]::TryParse((Get-Scalar $block 'port'), [ref]$nodePort) -or $nodePort -lt 1 -or $nodePort -gt 65535) { return $null }
            return @{ Host = $server; Port = $nodePort }
        }
    }
    return $null
}

function Invoke-Probe([string]$Url, [int]$TimeoutSeconds = 8, [string]$Secret, [string]$ProxyUrl, [switch]$ReadJson) {
    $handler = [System.Net.Http.HttpClientHandler]::new()
    $handler.AllowAutoRedirect = $false
    $handler.UseProxy = [bool]$ProxyUrl
    if ($ProxyUrl) { $handler.Proxy = [System.Net.WebProxy]::new($ProxyUrl) }
    $client = [System.Net.Http.HttpClient]::new($handler)
    $client.Timeout = [TimeSpan]::FromSeconds($TimeoutSeconds)
    $request = [System.Net.Http.HttpRequestMessage]::new([System.Net.Http.HttpMethod]::Get, $Url)
    if ($Secret) {
        # Keep credentials away from arbitrary endpoints, command lines, redirects and reports.
        $uri = [uri]$Url
        if ($uri.Scheme -ne 'http' -or $uri.Host -ne '127.0.0.1' -or $uri.UserInfo) { $client.Dispose(); $request.Dispose(); throw 'Unsafe authenticated endpoint' }
        $request.Headers.Authorization = [System.Net.Http.Headers.AuthenticationHeaderValue]::new('Bearer', $Secret)
    }
    $watch = [Diagnostics.Stopwatch]::StartNew()
    $response = $null
    try {
        $response = $client.SendAsync($request, [System.Net.Http.HttpCompletionOption]::ResponseHeadersRead).GetAwaiter().GetResult()
        $result = @{ http_status = [int]$response.StatusCode; elapsed_ms = $watch.ElapsedMilliseconds }
        if ($ReadJson -and $response.IsSuccessStatusCode) {
            # The local API bodies are small. Bound buffering and reject oversized responses.
            $bufferTask = $response.Content.LoadIntoBufferAsync(2097152)
            if (-not $bufferTask.Wait($TimeoutSeconds * 1000)) { throw [TimeoutException]::new('Response body timeout') }
            [void]$bufferTask.GetAwaiter().GetResult()
            $result.Data = ($response.Content.ReadAsStringAsync().GetAwaiter().GetResult() | ConvertFrom-Json)
        }
        return $result
    } catch {
        return @{ failure = (Get-FailureClass $_.Exception.ToString()); elapsed_ms = $watch.ElapsedMilliseconds }
    } finally {
        if ($null -ne $response) { $response.Dispose() }
        $request.Dispose(); $client.Dispose()
    }
}

function Get-TcpStatus([string]$Server, [int]$Port) {
    $socket = [Net.Sockets.TcpClient]::new()
    try {
        $task = $socket.ConnectAsync($Server, $Port)
        if (-not $task.Wait(5000)) { return 'timeout' }
        [void]$task.GetAwaiter().GetResult()
        return 'connected'
    } catch { return (Get-FailureClass $_.Exception.ToString()) }
    finally { $socket.Dispose() }
}

function Get-CoreLogClasses([Net.WebSockets.ClientWebSocket]$Socket) {
    $counts = @{}
    $cancel = [Threading.CancellationTokenSource]::new(1200)
    try {
        for ($i = 0; $i -lt 100; $i++) {
            $bytes = [byte[]]::new(16384)
            $message = $Socket.ReceiveAsync([ArraySegment[byte]]::new($bytes), $cancel.Token).GetAwaiter().GetResult()
            if ($message.MessageType -ne [Net.WebSockets.WebSocketMessageType]::Text -or -not $message.EndOfMessage) { break }
            $event = ([Text.Encoding]::UTF8.GetString($bytes, 0, $message.Count) | ConvertFrom-Json)
            $category = Get-FailureClass ([string]$event.payload)
            if ($category -ne 'other') { $counts[$category] = 1 + [int]$counts[$category] }
        }
    } catch { } finally { $cancel.Dispose() }
    return $counts
}

function Invoke-CapybaraDiagnostic {
    $report = [ordered]@{ schema = 1; timestamp = [DateTimeOffset]::Now.ToString('o'); os = [Environment]::OSVersion.VersionString; powershell = $PSVersionTable.PSVersion.ToString(); node_query = $NodeMatch }
    $socket = $null
    try {
        $report.processes = @{}
        foreach ($name in @('capybara', 'mihomo', 'v2rayN', 'xray', 'sing-box')) { $report.processes[$name] = @(Get-Process -Name $name -ErrorAction SilentlyContinue).Count }
        if (-not $RuntimePath) {
            foreach ($base in @($env:APPDATA, $env:LOCALAPPDATA)) {
                if ($base) {
                    $candidate = Join-Path $base 'us.taige.capybara/runtime.yaml'
                    if (Test-Path -LiteralPath $candidate) { $RuntimePath = $candidate; break }
                }
            }
        }
        if (-not $RuntimePath -or -not (Test-Path -LiteralPath $RuntimePath)) { $report.stage = 'runtime_missing_login_and_wait_for_nodes'; return $report }
        if ((Get-Item -LiteralPath $RuntimePath).Length -gt 2097152) { $report.stage = 'runtime_too_large'; return $report }
        $yaml = [IO.File]::ReadAllText($RuntimePath)
        $config = Get-LocalConfig $yaml
        $report.local_mixed_port = Get-TcpStatus '127.0.0.1' $config.Port
        if ($env:OS -eq 'Windows_NT') {
            $registry = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'
            $report.system_proxy = @{ enabled = ([int]$registry.ProxyEnable -ne 0); auto_config_present = [bool]$registry.AutoConfigURL; points_to_capybara = ([string]$registry.ProxyServer -match ('127\.0\.0\.1:' + $config.Port + '(;|$)')) }
        }
        $version = Invoke-Probe ($config.Base + '/version') -Secret $config.Secret -ReadJson
        $report.controller = @{ http_status = $version.http_status; failure = $version.failure }
        if (-not $version.Data) { $report.stage = 'controller_unavailable'; return $report }
        $report.core_version = [string]$version.Data.version
        $general = Invoke-Probe ($config.Base + '/configs') -Secret $config.Secret -ReadJson
        $report.mode = [string]$general.Data.mode
        $nodes = Invoke-Probe ($config.Base + '/proxies') -Secret $config.Secret -ReadJson
        $found = @($nodes.Data.proxies.PSObject.Properties | Where-Object { $_.Name.Contains($NodeMatch) -and $_.Value.type -notin @('Selector','URLTest','Fallback','Direct','Reject') })
        if ($found.Count -ne 1) { $report.stage = 'node_match_not_unique'; $report.matches = $found.Count; return $report }
        $node = $found[0]
        $report.node = $node.Name
        $report.node_type = [string]$node.Value.type
        $report.selected_groups = @($nodes.Data.proxies.PSObject.Properties | Where-Object { $_.Value.type -eq 'Selector' } | ForEach-Object { @{ group = $_.Name; selected = [string]$_.Value.now } })
        $endpoint = Get-NodeEndpoint $yaml $node.Name
        if ($endpoint) {
            $report.entry_tcp = Get-TcpStatus $endpoint.Host $endpoint.Port
            # No WS path, UUID, or subscription data is sent to the entry's public root.
            $report.entry_https = Invoke-Probe ('https://' + $endpoint.Host + ':' + $endpoint.Port + '/')
        }
        $report.resolver_https = @{}
        foreach ($resolver in @('doh.pub', 'dns.alidns.com')) { $report.resolver_https[$resolver] = Invoke-Probe ('https://' + $resolver + '/dns-query') }
        try {
            $socket = [Net.WebSockets.ClientWebSocket]::new()
            $socket.Options.Proxy = $null
            $socket.Options.SetRequestHeader('Authorization', 'Bearer ' + $config.Secret)
            $cancel = [Threading.CancellationTokenSource]::new(3000)
            try { [void]$socket.ConnectAsync([uri]($config.Base.Replace('http://','ws://') + '/logs?level=warning'), $cancel.Token).GetAwaiter().GetResult() } finally { $cancel.Dispose() }
            $report.log_capture = 'available'
        } catch { $report.log_capture = 'unavailable' }
        $report.node_tests = @()
        foreach ($test in @(@{ label='google_5s'; url='https://www.gstatic.com/generate_204'; ms=5000 }, @{ label='google_12s'; url='https://www.gstatic.com/generate_204'; ms=12000 }, @{ label='cloudflare_12s'; url='https://cp.cloudflare.com/generate_204'; ms=12000 })) {
            Write-Host ('Testing ' + $test.label + ' ...')
            $uri = $config.Base + '/proxies/' + [uri]::EscapeDataString($node.Name) + '/delay?url=' + [uri]::EscapeDataString($test.url) + '&timeout=' + $test.ms + '&expected=204'
            $probe = Invoke-Probe $uri -TimeoutSeconds ([int]($test.ms / 1000) + 2) -Secret $config.Secret -ReadJson
            $report.node_tests += @{ target=$test.label; http_status=$probe.http_status; delay_ms=$probe.Data.delay; elapsed_ms=$probe.elapsed_ms; failure=$probe.failure }
        }
        # Uses the current selection, not necessarily the requested diagnostic node. Record both above.
        $report.current_selection_proxy = Invoke-Probe 'https://www.gstatic.com/generate_204' -TimeoutSeconds 15 -ProxyUrl ('http://127.0.0.1:' + $config.Port)
        if ($socket -and $socket.State -eq [Net.WebSockets.WebSocketState]::Open) { $report.core_error_categories = Get-CoreLogClasses $socket }
        $report.stage = 'completed'
    } catch { $report.stage = 'diagnostic_incomplete'; $report.failure = Get-FailureClass $_.Exception.ToString() }
    finally { if ($socket) { $socket.Dispose() } }
    return $report
}

if ($MyInvocation.InvocationName -ne '.') {
    Write-Host 'Keep Capybara open and signed in. Checking connectivity; settings will not be changed.'
    $report = Invoke-CapybaraDiagnostic
    $json = $report | ConvertTo-Json -Depth 12
    [IO.File]::WriteAllText($OutputPath, $json, [Text.UTF8Encoding]::new($false))
    Write-Host ('Report saved: ' + $OutputPath)
    Write-Host 'Share only this JSON report, not runtime.yaml or raw logs.'
}

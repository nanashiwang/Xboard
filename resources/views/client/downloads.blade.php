<!doctype html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <meta name="referrer" content="no-referrer">
    <title>客户端下载 · {{ $title }}</title>
    <link rel="stylesheet" href="/assets/client-downloads.css?v={{ $assetVersion }}">
    <script defer src="/assets/client-downloads.js?v={{ $assetVersion }}"></script>
</head>
<body>
    <header class="topbar"><a class="brand" href="/#/dashboard">{{ $title }}</a><a href="/#/dashboard">返回用户中心 <span aria-hidden="true">↗</span></a></header>
    <main>
        <div class="intro"><span class="eyebrow">CLIENT DOWNLOADS</span><h1>在你的设备上开始使用</h1><p>选择设备，安装客户端，再导入你的订阅。</p></div>
        <ol class="steps" aria-label="使用步骤"><li><span>1</span>选择设备</li><li><span>2</span>下载安装</li><li><span>3</span>导入订阅</li></ol>
        <nav class="platforms" aria-label="设备类型">
            @foreach($clients as $platform => $client)
                <a href="#{{ $platform }}" data-platform="{{ $platform }}">{{ $client['platform'] }}</a>
            @endforeach
        </nav>
        <p id="device-hint" class="device-hint">请选择要安装客户端的设备。</p>
        @foreach($clients as $platform => $client)
        <section class="client" id="{{ $platform }}" data-client="{{ $client['id'] }}" aria-labelledby="name-{{ $platform }}">
            <div class="install panel">
                <div class="section-label">02 / 下载安装</div>
                <div class="client-heading"><span class="client-icon" aria-hidden="true">{{ $platform === 'ios' ? 'S' : 'C' }}</span><div><h2 id="name-{{ $platform }}">{{ $client['name'] }}</h2><p>{{ $client['version'] }} <span class="dot">·</span> 开源客户端</p></div></div>
                <p class="requirement">{{ $client['requirement'] }}</p>
                <div class="packages">
                    @foreach($client['packages'] as $package)
                    <div class="package">
                        <a class="download" href="{{ $package['url'] }}" @if(isset($package['sha256'])) download @else target="_blank" rel="noopener noreferrer" @endif><span aria-hidden="true">↓</span> {{ $package['label'] }}</a>
                        @if(isset($package['sha256']))
                        <div class="package-meta"><span>{{ $package['size'] }}</span><a href="{{ $package['official_url'] }}" target="_blank" rel="noopener noreferrer">官方备用下载 ↗</a><details><summary>校验值</summary><code>{{ $package['sha256'] }}</code></details></div>
                        @endif
                    </div>
                    @endforeach
                </div>
                <p class="note">{{ $client['note'] }}</p>
                @if(isset($client['releases']))
                <p><a class="source" href="{{ $client['releases'] }}" target="_blank" rel="noopener noreferrer">其他版本与架构 ↗</a></p>
                @endif
                <a class="source" href="{{ $client['source'] }}" target="_blank" rel="noopener noreferrer">查看开源项目与许可证 ↗</a>
            </div>
            <div class="connect panel">
                <div class="section-label">03 / 导入订阅</div>
                <h2>装好后，只差一步</h2><p class="guide">{{ $client['guide'] }}</p>
                <div class="auth-state"><p>登录后可导入你自己的订阅。</p><a class="button secondary" href="/#/login?redirect=%2Fdashboard">前往登录</a></div>
                <div class="import-controls" hidden>
                    <button class="button prepare" type="button">获取我的订阅</button>
                    <div class="import-ready" hidden>
                        <a class="button launch">一键导入 {{ $client['name'] }}</a>
                        <button class="button secondary copy" type="button">复制订阅地址</button>
                        <p class="fallback">没有打开客户端？确认已安装并打开过一次，或复制地址后在客户端添加远程订阅。</p>
                        <details class="manual"><summary>手动导入地址</summary><input class="subscription" type="text" readonly aria-label="个人订阅地址" autocomplete="off" spellcheck="false"></details>
                        <p class="privacy">订阅地址仅供你本人使用，请勿公开分享。</p>
                    </div>
                </div>
                <p class="status" role="status" aria-live="polite"></p>
                <a class="account-link" href="/#/dashboard">查看套餐和剩余流量 →</a>
            </div>
        </section>
        @endforeach
        <aside class="help"><h2>从下载到连接</h2><div><p><strong>安装后回到这里</strong>浏览器会询问是否打开客户端，确认后在客户端保存配置。</p><p><strong>选择配置并连接</strong>导入后选择刚添加的订阅，按客户端提示开启代理或 VPN。</p><p><strong>遇到问题</strong>先更新订阅、检查套餐与流量，再查看<a href="/#/knowledge">使用文档</a>。</p></div></aside>
        <noscript><p>当前浏览器未启用 JavaScript。你仍可下载客户端，导入订阅请回到用户中心。</p></noscript>
    </main>
    <footer>客户端下载与订阅由 {{ $title }} 提供 <span>·</span> 客户端由各开源项目维护</footer>
</body>
</html>

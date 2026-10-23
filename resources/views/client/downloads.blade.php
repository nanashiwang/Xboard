<!doctype html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <meta name="referrer" content="no-referrer">
    <title>卡皮巴拉客户端下载 · {{ $title }}</title>
    <link rel="icon" href="/assets/capybara-home/icon.webp">
    <link rel="stylesheet" href="/assets/client-downloads.css?v={{ $assetVersion }}">
    <script defer src="/assets/client-downloads.js?v={{ $assetVersion }}"></script>
</head>
<body>
    <header class="topbar"><a class="brand" href="/"><img src="/assets/capybara-home/icon.webp" width="36" height="36" alt="">卡皮巴拉</a><a href="/#/dashboard">用户中心 <span aria-hidden="true">↗</span></a></header>
    <main>
        <div class="intro"><span class="eyebrow">CAPYBARA FOR DESKTOP</span><h1>把卡皮巴拉带到你的电脑</h1><p>安装后登录本站账号，就能查看流量、选择线路并连接。</p><p class="mobile-note">Windows、macOS、Linux 已提供测试版；手机暂使用下方第三方客户端。</p></div>
        <nav class="platforms" aria-label="设备类型">
            @foreach($clients as $platform => $client)
                @if($platform !== 'clash-verge')
                <a href="#{{ $platform }}" data-platform="{{ $platform }}">{{ $client['platform'] }}</a>
                @endif
            @endforeach
        </nav>
        <p id="device-hint" class="device-hint">请选择要安装客户端的设备。</p>
        @foreach($clients as $platform => $client)
        <section class="client" id="{{ $platform }}" data-client="{{ $client['id'] }}" data-flow="{{ $client['flow'] }}" aria-labelledby="name-{{ $platform }}">
            <div class="install panel">
                <div class="section-label">{{ $client['flow'] === 'account' ? '卡皮巴拉官方桌面客户端' : '第三方开源客户端 · 订阅导入' }}</div>
                <div class="client-heading">@if($client['flow'] === 'account')<img class="client-icon" src="/assets/capybara-home/icon.webp" width="56" height="56" alt="">@else<span class="client-icon" aria-hidden="true">{{ $platform === 'ios' ? 'S' : 'C' }}</span>@endif<div><h2 id="name-{{ $platform }}">{{ $client['name'] }}</h2><p>{{ $client['version'] }} <span class="dot">·</span> {{ $client['flow'] === 'account' ? 'Alpha 测试版' : '由第三方项目维护' }}</p></div></div>
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
                <p><a class="source" href="{{ $client['releases'] }}" target="_blank" rel="noopener noreferrer">{{ $client['flow'] === 'account' ? '版本说明与安装包' : '其他版本与架构' }} ↗</a></p>
                @endif
                <a class="source" href="{{ $client['source'] }}" target="_blank" rel="noopener noreferrer">查看开源项目与许可证 ↗</a>
            </div>
            <div class="connect panel">
                @if($client['flow'] === 'account')
                <div class="section-label">安装 → 登录 → 连接</div>
                <h2>用你的账号，直接出发</h2><p class="guide">{{ $client['guide'] }}</p>
                <ul class="benefits"><li><strong>流量状态自动同步</strong><span>每 30 秒检查剩余流量与到期状态，耗尽时明确提示。</span></li><li><strong>线路配置自动更新</strong><span>连接前核对配置，连接期间每小时更新。</span></li><li><strong>从第一次连接开始</strong><span>先关闭其他代理客户端，再在卡皮巴拉中连接。</span></li></ul>
                <a class="button secondary" href="/#/register">还没有账号？前往注册</a>
                <p class="preview-note">当前通过系统代理连接，暂不支持 TUN。测试版需手动安装更新；流量统计可能存在上报延迟。</p>
                @else
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
                @endif
                <a class="account-link" href="/#/dashboard">查看套餐和剩余流量 →</a>
            </div>
        </section>
        @endforeach
        <p class="alternative">已在使用 Clash，或需要其他桌面方案？<a href="#clash-verge" data-platform="clash-verge">第三方客户端下载与导入 →</a></p>
        <aside class="help"><h2>连接前的小提醒</h2><div><p><strong>电脑端直接登录</strong>卡皮巴拉使用本站账号，连接前请确认套餐有效且有剩余流量。</p><p><strong>手机端导入订阅</strong>目前没有卡皮巴拉手机版，请按 Android / iOS 页签中的第三方客户端指引操作。</p><p><strong>遇到问题</strong>先看客户端提示、套餐与流量，再查看<a href="/#/knowledge">使用文档</a>，或<a href="/#/ticket">提交工单</a>。</p></div></aside>
        <noscript><p>当前浏览器未启用 JavaScript，所有设备的安装包均列在上方。卡皮巴拉安装后直接登录；第三方订阅导入请回到用户中心。</p></noscript>
    </main>
    <footer>卡皮巴拉 · 与你一起探索 <span>·</span> <a href="/">返回首页</a> <span>·</span> <a href="/downloads/SHA256SUMS.txt">安装包校验清单</a></footer>
</body>
</html>

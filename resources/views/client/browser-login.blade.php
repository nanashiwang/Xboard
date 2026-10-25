<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>登录卡皮巴拉客户端</title>
  <link rel="icon" href="/assets/capybara-home/icon.webp">
  <link rel="stylesheet" href="/assets/desktop-login.css?v=1">
  <script defer src="/assets/desktop-login.js?v=2"></script>
</head>
<body>
  <main>
    <a class="brand" href="/">CAPYBARA <span>卡皮巴拉</span></a>
    <img class="mascot" src="/assets/capybara-home/icon.webp" alt="卡皮巴拉">
    <p class="eyebrow">连接，从这里开始</p>
    <h1>登录桌面客户端</h1>
    <p id="message" role="status" aria-live="polite">正在检查授权请求…</p>
    <section id="details" hidden>
      <div><span>当前账号</span><strong id="account"></strong></div>
      <div><span>登录设备</span><strong id="device"></strong></div>
      <p>仅在你刚刚点击客户端“登录”时授权。授权后，客户端可使用账号套餐和线路。</p>
    </section>
    <div id="actions">
      <button id="approve" hidden>授权并返回客户端</button>
      <button id="login" hidden>登录官网并继续</button>
      <button id="register" class="secondary" hidden>注册账号并继续</button>
      <button id="reject" class="secondary" hidden>取消授权</button>
      <button id="retry" class="secondary" hidden>重试</button>
    </div>
    <p class="footnote">已登录官网时无需再次输入密码。授权有效期为 5 分钟。</p>
    <noscript>请启用 JavaScript 后重新打开此页。</noscript>
  </main>
</body>
</html>

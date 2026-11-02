<!doctype html>
<html lang="zh-CN" data-xboard-page="home">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <meta name="description" content="{{ ($entry_gate ?? false) ? '卡皮巴拉应用入口' : '与卡皮巴拉一起畅游全球网络。了解套餐、下载客户端，轻松开启你的网络探索。' }}" />
  <meta name="theme-color" content="{{ ($entry_gate ?? false) ? '#ffffff' : '#eaf5ff' }}" />
  <title>{{$title}}</title>
  <script>document.documentElement.dataset.xboardPage = location.hash.indexOf('#/') === 0 ? 'panel' : 'home';</script>
  <link rel="icon" type="image/webp" href="/assets/capybara-home/icon.webp" />
  <link rel="stylesheet" href="/assets/capybara-home/{{ ($entry_gate ?? false) ? 'entry' : 'home' }}.css?v=1" />
</head>
<body>
  <script>
    window.routerBase = "/";
    window.settings = {{ Illuminate\Support\Js::from([
      'title' => $title,
      'assets_path' => '/theme/' . $theme . '/assets',
      'theme' => ['color' => $theme_config['theme_color'] ?? 'default'],
      'version' => $version,
      'background_url' => $theme_config['background_url'] ?? '',
      'description' => $description,
      'i18n' => ['zh-CN', 'en-US', 'ja-JP', 'vi-VN', 'ko-KR', 'zh-TW', 'fa-IR'],
      'logo' => $logo,
    ]) }};
  </script>
  @if($entry_gate ?? false)
    @include('home.entry')
  @else
    @include('home.capybara')
  @endif
  <div id="app"><noscript>登录和用户中心需要启用 JavaScript。<a href="/">返回首页</a></noscript></div>
  <script defer src="/assets/capybara-home/home.js?v={{$version}}" data-panel-src="/theme/{{$theme}}/assets/umi.js"></script>
  <script defer src="/assets/desktop-login-return.js?v=1"></script>
  {!! $theme_config['custom_html'] ?? '' !!}
</body>
</html>

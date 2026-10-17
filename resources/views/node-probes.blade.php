<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <meta name="referrer" content="no-referrer"><title>节点质量 · {{ $title }}</title>
  <link rel="stylesheet" href="/assets/node-probes.css?v=1">
  <script src="/assets/node-probes.js?v=1" defer></script>
</head>
<body data-admin-path="{{ $secure_path }}" @if(request()->boolean('embedded')) class="embedded" data-theme="{{ request('theme') === 'dark' ? 'dark' : 'light' }}" @endif>
<header><a href="/{{ $secure_path }}">← 返回管理后台</a><span>Xboard · 网络观测</span></header>
<main>
  <section class="intro"><div><p class="eyebrow">NODE QUALITY</p><h1>节点质量</h1><p>从探针所在网络，检查用户实际经过的节点线路。</p></div><button id="refresh">刷新结果</button></section>
  <div id="message" role="status" aria-live="polite">正在读取探针…</div>
  <section id="workspace" hidden>
    <div class="toolbar"><label>探测位置 <select id="location"><option value="">全部位置</option></select></label><span id="updated"></span></div>
    <div id="probes"></div>
    <details class="card" id="create-panel"><summary>添加探针</summary>
      <p>先在用户管理创建独立的普通监控账号并分配权限组、流量和有效期。检测计入该账号用量，速度受其限速影响。专属分配账号暂不支持。</p>
      <form id="create-form">
        <div class="fields"><label>探针名称<input name="name" required maxlength="80" placeholder="例如 nas"></label><label>所在网络<input name="location" required maxlength="120" placeholder="例如 家庭网络 / NAS"></label><label>监控账号 ID<input name="user_id" type="number" min="1" required></label></div>
        <fieldset><legend>检测公开节点</legend><div id="server-options"></div></fieldset>
        <p class="muted">每轮完成后等待 60 秒；每 30 分钟每节点各传输 256 KiB 上下行，另有 HTTPS 检查流量。结果是小样本速率，不能作为线路带宽上限。</p>
        <button type="submit">创建探针</button>
      </form>
    </details>
    <section class="card guide"><h2>如何判断稳定性</h2><p>连续 3 轮两个 HTTPS 目标均失败记为故障；连续 2 轮全部成功记为正常。部分失败显示波动。探针或节点停止上报后显示数据过期，不继续显示正常。</p><p>成功率按最近 24 个小时桶内的实际 HTTP 请求计算，缺失时段不计为成功；详细记录保留 24 小时、小时统计保留 30 天。多个位置应分开比较。</p><p>出口 IP 可辅助核对落地点；入口地址显示订阅配置值，仍需结合客户端实际连接或入口日志确认所用入口。</p></section>
  </section>
  <section id="auth" class="card" hidden><h2>需要管理员登录</h2><p>请先登录管理后台，再返回此页。</p><a href="/{{ $secure_path }}">前往登录</a></section>
</main>
<dialog id="credentials"><h2>保存探针配置</h2><p>令牌只显示一次。将以下内容保存为 NAS 探针目录中的 agent.json，文件权限设为 600。不要分享或提交到仓库。</p><textarea id="agent-config" rows="7" readonly aria-label="探针配置"></textarea><p>运行方式见仓库 docs/zh-CN/installation/node-probes.md。</p><button id="close-credentials">已保存，关闭</button></dialog>
<dialog id="history"><div class="toolbar"><h2 id="history-title">检测明细</h2><button id="close-history">关闭</button></div><div id="history-content"></div></dialog>
</body></html>

(() => {
  'use strict';
  const path = document.body.dataset.adminPath;
  if (!path) return;
  const labels = {healthy:'正常',degraded:'波动',down:'故障',config_error:'配置异常',unknown:'待采样',stale:'数据过期',disabled:'停用'};
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let widget, probes = [], selected = '', loading = false, auth = '', rejectedToken = '', request = new AbortController();
  const token = () => { try { const t = JSON.parse(localStorage.getItem('XBOARD_ACCESS_TOKEN')); return t && (!t.expire || t.expire > Date.now()) ? t.value : ''; } catch { return ''; } };
  const home = () => !location.hash || location.hash.split('?')[0] === '#/';
  const date = t => t ? new Date(t*1000).toLocaleString('zh-CN',{hour12:false}) : '待采样';
  function openDetails(probe, node) {
    const dialog = document.getElementById('node-probe-dialog');
    const query = new URLSearchParams({embedded:'1',theme:document.documentElement.classList.contains('dark')?'dark':'light'});
    if (probe && node) { query.set('probe',probe); query.set('node',node); }
    document.getElementById('node-probe-frame').src = '/' + path + '/node-probes?' + query;
    dialog.showModal();
  }
  document.getElementById('node-probe-dialog-close').onclick = () => document.getElementById('node-probe-dialog').close();
  document.getElementById('node-probe-dialog').addEventListener('close', () => { document.getElementById('node-probe-frame').src = 'about:blank'; });
  function reset() {
    request.abort(); request = new AbortController(); probes = []; selected = ''; loading = false;
    document.getElementById('node-probe-dialog').close();
    if (widget) widget.remove(); widget = null;
  }
  function render(stale=false) {
    if (!widget?.isConnected) return;
    const p = probes.find(p => String(p.id) === selected) || probes[0];
    const content = widget.querySelector('[data-content]');
    const select = widget.querySelector('select');
    select.innerHTML = probes.map(p => `<option value="${p.id}">${esc(p.name)} · ${esc(p.location)}</option>`).join('');
    select.hidden = !probes.length;
    if (!p) { content.innerHTML = '<div class="np-empty">尚未接入探针。NAS 启动并上报后，这里将展示节点状态与上传下载结果。</div>'; return; }
    selected = String(p.id); select.value = selected;
    const nodes = p.nodes;
    const abnormal = nodes.filter(n => ['down','degraded','config_error'].includes(n.status)).length;
    const pending = nodes.filter(n => ['unknown','stale'].includes(n.status)).length;
    const requests = nodes.reduce((a,n) => a+n.requests,0), successes = nodes.reduce((a,n) => a+n.successes,0);
    const speed = (n,id) => { const c = (n.transfers || []).find(c => c.id===id); return c ? (c.ok ? esc(c.mbps)+' Mbps' : '<span class="np-bad">失败</span>') : '—'; };
    content.innerHTML = `<div class="np-metrics"><div><small>探针通信</small><strong>${stale?'待确认':(p.enabled?(p.online?'在线':'未上报 / 失联'):'已停用')}</strong></div><div><small>异常 / 检测节点</small><strong>${stale?'—':abnormal} <em>/ ${nodes.length}</em></strong><small>${stale?nodes.length:pending} 个节点状态待确认</small></div><div><small>本位置 HTTP 成功率</small><strong>${requests?(successes/requests*100).toFixed(1)+'%':'—'}</strong><small>${successes}/${requests} 次 · 最近 24 个小时桶</small></div><div><small>监控账号</small><strong>${p.account.speed_limit_mbps?esc(p.account.speed_limit_mbps)+' Mbps':'未设限速'}</strong><small>剩余 ${(p.account.remaining_bytes/1073741824).toFixed(2)} GiB</small></div></div><div class="np-scroll"><table><thead><tr><th>节点</th><th>当前状态</th><th>HTTP 成功率</th><th>上传小样本</th><th>下载小样本</th><th>最近传输</th></tr></thead><tbody>${nodes.map(n=>`<tr><td><button data-node="${n.id}">${esc(n.name)}</button></td><td><span class="np-${stale?'stale':esc(n.status)}">${stale?'数据过期':labels[n.status]}</span></td><td>${n.availability===null?'—':esc(n.availability)+'%'}</td><td>${speed(n,'upload')}</td><td>${speed(n,'download')}</td><td>${stale||n.transfers_stale?'历史 · ':''}${date(n.transfer_checked_at)}</td></tr>`).join('')}</tbody></table></div><p class="np-foot">${esc(p.location)} · 最后通信 ${date(p.last_seen_at)}。点击节点查看失败原因与历史。小样本速率包含连接开销，不代表带宽上限。</p>`;
    content.querySelectorAll('[data-node]').forEach(b => { b.onclick = () => openDetails(p.id,b.dataset.node); });
  }
  async function load() {
    if (loading || !widget?.isConnected || !home()) return;
    const current = token();
    if (!current) { reset(); return; }
    if (auth && auth !== current) { reset(); return; }
    auth = current; loading = true;
    const status = widget.querySelector('[data-status]');
    try {
      const response = await fetch('/api/v2/'+path+'/node-probes', {headers:{Authorization:auth,Accept:'application/json'},cache:'no-store',signal:request.signal});
      if (auth !== token()) { reset(); return; }
      if ([401,403].includes(response.status)) { rejectedToken=auth; reset(); return; }
      if (!response.ok) throw new Error('unavailable');
      probes = (await response.json()).data.probes;
      if (!widget?.isConnected) return;
      render(); status.textContent = '每 30 秒刷新 · '+new Date().toLocaleTimeString('zh-CN');
    } catch(e) {
      if (e.name !== 'AbortError' && widget?.isConnected) { render(true); status.textContent = '暂时无法更新，已有数据已标记为过期。'; }
    } finally { loading = false; }
  }
  function mount() {
    const current = token();
    if (auth && auth !== current) { reset(); auth=current; }
    if (!current || current===rejectedToken || location.hash.startsWith('#/sign-in')) { if (widget) reset(); return; }
    const nav = document.querySelector('nav a[href="#/"]');
    if (nav && !document.getElementById('node-probe-nav')) {
      const link = document.createElement('a'); link.id='node-probe-nav'; link.href='#node-quality'; link.textContent='节点质量'; link.className=nav.className.split(' ').filter(c=>!['bg-secondary','text-secondary-foreground','shadow-sm','hover:bg-secondary/80'].includes(c)).join(' ')+' hover:bg-accent'; link.removeAttribute('aria-current');
      link.onclick=e=>{ e.preventDefault(); openDetails(); }; nav.after(link);
    }
    if (!home()) { if (widget) { widget.remove(); widget=null; } return; }
    // The upstream admin is a pinned dist submodule. Only attach our owned card to its dashboard content;
    // never rewrite React's children or compiled assets. Recheck this boundary when updating that submodule.
    const content = document.querySelector('main .space-y-6');
    if (!content || document.getElementById('node-probe-dashboard')) return;
    widget=document.createElement('section'); widget.id='node-probe-dashboard'; widget.className='np-dashboard';
    widget.innerHTML='<div class="np-heading"><div><h2>节点质量监控</h2><p>NAS 实测用户访问线路 · 上传与下载分开检测</p></div><div class="np-actions"><select aria-label="看板探测位置"></select><button data-open>探针管理与明细</button></div></div><p class="np-foot" data-status role="status">正在读取探针…</p><div data-content></div>';
    widget.querySelector('[data-open]').onclick=()=>openDetails();
    widget.querySelector('select').onchange=e=>{selected=e.target.value;render();};
    content.prepend(widget); load();
  }
  const root=document.getElementById('root');
  if(root) new MutationObserver(mount).observe(root,{childList:true,subtree:true});
  window.addEventListener('hashchange',mount);
  window.addEventListener('storage',e=>{if(e.key==='XBOARD_ACCESS_TOKEN'||e.key===null){reset();auth='';mount();}});
  setInterval(()=>{mount();if(!document.hidden)load();},30000);
  mount();
})();

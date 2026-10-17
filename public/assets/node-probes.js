(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const base = '/api/v2/' + document.body.dataset.adminPath + '/node-probes';
  const names = {healthy:'正常',degraded:'波动 / 确认中',down:'故障',config_error:'配置异常',unknown:'尚无数据',stale:'数据过期',disabled:'已停用'};
  const errors = {timeout:'超时',dns:'DNS 失败',connect:'连接失败',tls:'TLS 失败',http:'HTTP 异常',incomplete:'传输不完整',proxy:'代理失败',unknown:'检测失败',account_unavailable:'监控账号不可用或节点无权限',node_unavailable:'节点不可用',unsupported_protocol:'协议暂不支持',insecure_tls:'节点未启用证书校验',core_unavailable:'探针缺少内核',core_config:'内核配置不兼容'};
  let detailOpened = false;
  let data, token = '', busy = false, controller = new AbortController();
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const date = t => t ? new Date(t * 1000).toLocaleString('zh-CN', {hour12:false}) : '尚无数据';
  const val = (v, suffix='') => v === null || v === undefined ? '—' : esc(v) + suffix;
  function readToken() { try { const t = JSON.parse(localStorage.getItem('XBOARD_ACCESS_TOKEN')); return t && (!t.expire || t.expire > Date.now()) ? t.value : ''; } catch { return ''; } }
  function resetAuth() { controller.abort(); controller = new AbortController(); data = null; $('probes').replaceChildren(); $('server-options').replaceChildren(); $('workspace').hidden = true; $('auth').hidden = false; $('credentials').close(); $('history').close(); $('agent-config').value = ''; }
  function message(text, error=false) { $('message').textContent = text.replace('Failed to fetch', '连接面板失败，请检查网络。'); $('message').className = error ? 'error' : ''; }
  async function api(path='', body) {
    if (!token || token !== readToken()) { resetAuth(); throw new Error('登录已失效，请重新登录。'); }
    const response = await fetch(base + path, {method:body ? 'POST' : 'GET', headers:{Authorization:token, Accept:'application/json', ...(body ? {'Content-Type':'application/json'} : {})}, body:body ? JSON.stringify(body) : undefined, cache:'no-store', signal:controller.signal});
    if (token !== readToken()) { resetAuth(); throw new Error('登录已切换，请刷新。'); }
    if ([401,403].includes(response.status)) { resetAuth(); throw new Error('需要有效的管理员登录。'); }
    const result = await response.json();
    if (!response.ok) throw new Error(Object.values(result.errors || {}).flat().join('；') || result.message || '请求失败，请重试。');
    return result.data;
  }
  function render() {
    const selected = $('location').value;
    const probes = data.probes.filter(p => !selected || p.location === selected);
    $('probes').innerHTML = probes.length ? probes.map(p => `<section class="card"><div class="toolbar"><div><h2>${esc(p.name)} <span class="badge ${p.online ? 'healthy':'stale'}">${p.unverified ? '通信状态待确认' : (p.enabled ? (p.online ? '探针在线':'等待探针 / 已失联'):'探针停用')}</span></h2><span>${esc(p.location)}</span></div><div class="actions"><button data-toggle="${p.id}" data-enabled="${!p.enabled}">${p.enabled?'停用':'启用'}</button><button data-rotate="${p.id}">轮换令牌</button></div></div><div class="meta"><span>最后通信 ${date(p.last_seen_at)}</span><span>账号 #${p.user_id} · 限速 ${p.account.speed_limit_mbps ? val(p.account.speed_limit_mbps, ' Mbps'):'未设'}</span><span>剩余 ${(p.account.remaining_bytes/1073741824).toFixed(2)} GiB</span><span>探针 ${esc(p.agent_version || '—')}</span></div><div class="table-wrap"><table><thead><tr><th>节点 / 配置入口</th><th>状态 / 最新采样</th><th>HTTP 成功率</th><th>平均耗时</th><th>上下行小样本速率</th><th>出口 IP</th><th></th></tr></thead><tbody>${p.nodes.map(n => `<tr><td>${esc(n.name)}<small>${esc(n.host || '—')}</small></td><td><span class="badge ${esc(n.status)}">${names[n.status] || esc(n.status)}</span><small>${n.latest?.error ? esc(errors[n.latest.error] || n.latest.error) : date(n.checked_at)}</small>${n.latest?.exit_mismatch?'<small>出口 IP 与预期不同</small>':''}</td><td>${val(n.availability,'%')}<small>${n.successes} / ${n.requests} 次</small></td><td>${val(n.latency_ms,' ms')}</td><td>${(n.transfers || []).map(c => `${c.id==='upload'?'↑':'↓'} ${c.ok ? val(c.mbps,' Mbps') : esc(errors[c.error] || '失败')}`).join('　') || '—'}<small>完成 ↑ ${n.upload_successes}/${n.uploads}　↓ ${n.download_successes}/${n.downloads}</small><small>${n.transfers_stale?'历史 / 待更新 · ':''}${date(n.transfer_checked_at)}</small></td><td>${esc(n.exit_ip || '—')}</td><td><button data-history="${p.id}:${n.id}">明细</button></td></tr>`).join('')}</tbody></table></div></section>`).join('') : '<section class="card empty"><h2>还没有探针结果</h2><p>添加探针并在 NAS 启动后，这里将显示真实线路检测结果。</p></section>';
  }
  async function load() {
    if (busy) return;
    token = readToken();
    if (!token) { resetAuth(); message('登录后查看节点质量。'); return; }
    busy = true; $('refresh').disabled = true;
    try {
      data = await api(); $('auth').hidden = true; $('workspace').hidden = false;
      const selected = $('location').value;
      $('location').innerHTML = '<option value="">全部位置</option>' + [...new Set(data.probes.map(p => p.location))].map(l => `<option>${esc(l)}</option>`).join('');
      $('location').value = selected;
      if (!$('location').value) $('location').value = '';
      const checked = new Set([...document.querySelectorAll('[name=server]:checked')].map(e => e.value));
      $('server-options').innerHTML = data.servers.map(s => `<label><input type="checkbox" name="server" value="${s.id}" ${checked.has(String(s.id))?'checked':''}>${esc(s.name)} (#${s.id})</label>`).join('');
      render(); const query = new URLSearchParams(location.search); if (!detailOpened && /^\d+$/.test(query.get('probe') || '') && /^\d+$/.test(query.get('node') || '')) { detailOpened = true; document.querySelector(`[data-history="${query.get('probe')}:${query.get('node')}"]`)?.click(); } $('updated').textContent = '更新于 ' + new Date().toLocaleTimeString('zh-CN'); message('自动刷新间隔 30 秒 · 数据按探测位置分别统计');
    } catch(e) { if (e.name !== 'AbortError') { if (data) { data.probes.forEach(p => {p.online=false; p.unverified=true; p.nodes.forEach(n => {n.transfers_stale=true; if(n.status!=='disabled') n.status='stale';});}); render(); } message(e.message + ' 已显示结果未能更新。', true); } }
    finally { busy = false; $('refresh').disabled = false; }
  }
  function credentials(config) { config.panel_url = location.origin; $('agent-config').value = JSON.stringify(config, null, 2); $('credentials').showModal(); }
  $('refresh').onclick = load; $('location').onchange = render;
  $('close-credentials').onclick = () => $('credentials').close();
  $('credentials').addEventListener('close', () => { $('agent-config').value = ''; });
  $('close-history').onclick = () => $('history').close();
  $('create-form').onsubmit = async e => {
    e.preventDefault(); const form = e.target; const button = form.querySelector('button'); button.disabled = true;
    try { const fields = new FormData(form); const server_ids = [...document.querySelectorAll('[name=server]:checked')].map(e => Number(e.value)); if (!server_ids.length) throw new Error('至少选择一个节点。'); const r = await api('', {name:fields.get('name'),location:fields.get('location'),user_id:Number(fields.get('user_id')),server_ids}); credentials(r.agent_config); form.reset(); await load(); }
    catch(e) { message(e.message,true); } finally {button.disabled=false;}
  };
  $('probes').onclick = async e => {
    const button = e.target.closest('button'); if (!button) return;
    button.disabled = true;
    try {
      if (button.dataset.toggle) { await api('/' + button.dataset.toggle + '/enabled', {enabled:button.dataset.enabled === 'true'}); await load(); }
      if (button.dataset.rotate) { if (!confirm('轮换后旧令牌立即失效，NAS 需要更新配置。继续？')) return; credentials((await api('/' + button.dataset.rotate + '/rotate', {})).agent_config); await load(); }
      if (button.dataset.history) {
        const [probe, node] = button.dataset.history.split(':'); const p = data.probes.find(p => String(p.id) === probe); const n = p.nodes.find(n => String(n.id) === node);
        $('history-title').textContent = p.location + ' · ' + n.name; $('history-content').textContent = '正在读取…'; $('history').showModal();
        const h = await api('/' + probe + '/history/' + node);
        $('history-content').innerHTML = `<p>24 小时成功请求 P95：${val(h.latency_p95_ms,' ms')}。超时和失败单独列出，不包含在成功耗时内。</p><h3>状态变化</h3>${h.events.length ? h.events.slice(0,20).map(v => `<p>${date(v.created_at)} · ${names[v.from_status]} → ${names[v.to_status]}</p>`).join(''):'<p>尚无状态变化。</p>'}<h3>最近检测（最多 200 轮）</h3><div class="table-wrap"><table><thead><tr><th>时间</th><th>目标</th><th>结果</th><th>耗时</th><th>传输字节</th><th>小样本速率</th></tr></thead><tbody>${h.samples.map(s => s.checks.error ? `<tr><td>${date(s.checked_at)}</td><td colspan="5">${esc(errors[s.checks.error] || s.checks.error)}</td></tr>` : s.checks.checks.map(c => `<tr><td>${date(s.checked_at)}</td><td>${esc(c.id)}</td><td>${c.ok?'成功':esc(errors[c.error] || '失败')} (${c.status})</td><td>${val(c.ms,' ms')}</td><td>${c.bytes}</td><td>${val(c.mbps,' Mbps')}</td></tr>`).join('')).join('') || '<tr><td colspan="6">尚无检测记录</td></tr>'}</tbody></table></div><h3>30 天小时统计</h3><div class="table-wrap"><table><thead><tr><th>时段</th><th>轮数</th><th>HTTP 成功 / 总数</th><th>上传完成 / 总数</th><th>下载完成 / 总数</th></tr></thead><tbody>${h.hours.slice().reverse().map(v=>`<tr><td>${date(v.hour)}</td><td>${v.rounds}</td><td>${v.successes}/${v.requests}</td><td>${v.upload_successes}/${v.uploads}</td><td>${v.download_successes}/${v.downloads}</td></tr>`).join('') || '<tr><td colspan="5">尚无统计</td></tr>'}</tbody></table></div>`;
      }
    } catch(e) { message(e.message,true); if ($('history').open) $('history-content').textContent = '读取失败，请关闭后重试。'; }
    finally { button.disabled=false; }
  };
  window.addEventListener('storage', e => { if (e.key === 'XBOARD_ACCESS_TOKEN' || e.key === null) { resetAuth(); load(); } });
  setInterval(() => { if (token !== readToken()) resetAuth(); if (!document.hidden) load(); },30000);
  load();
})();

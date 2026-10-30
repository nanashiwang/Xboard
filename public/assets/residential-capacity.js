(() => {
  'use strict';
  const path = document.body.dataset.adminPath;
  if (!path) return;
  let panel, request, auth = '', nextRefresh = 0;
  const token = () => {
    try {
      const stored = JSON.parse(localStorage.getItem('XBOARD_ACCESS_TOKEN'));
      return stored && (!stored.expire || stored.expire > Date.now()) ? stored.value : '';
    } catch { return ''; }
  };
  const home = () => ['', '#', '#/'].includes(location.hash);
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function remove() {
    request?.abort(); request = null;
    panel?.remove(); panel = null; nextRefresh = 0;
  }
  function advice(plan) {
    if (!plan.selling) return '套餐已停售';
    if (plan.capacity_limit !== null && plan.occupied >= plan.capacity_limit) return '套餐销售上限已满';
    if (!plan.primary_capacity) return '暂无主用出口，请补充节点';
    if (!plan.available_slots) return plan.exits.some(e => e.enabled && !e.standby && e.free_slots > 0)
      ? '有空位的节点暂不可用，请检查健康状态' : '主用出口已满，请补充节点';
    return `当前还可新增 ${plan.available_slots} 个订阅`;
  }
  function render(data, target) {
    const plans = data.plans;
    const sum = key => plans.reduce((n, plan) => n + plan[key], 0);
    target.querySelector('.rc-time').textContent = '更新于 ' + new Date(data.checked_at * 1000).toLocaleTimeString();
    const stats = [['有效订阅', sum('subscribers')], ['已分配订阅', sum('assigned_subscribers')], ['订单预留', sum('reserved')], ['当前可新增', sum('available_slots')]];
    target.querySelector('.rc-data').innerHTML = `
      <div class="rc-stats">${stats.map(([label, count]) => `<div><span>${label}</span><strong>${count}<small> 人</small></strong></div>`).join('')}</div>
      ${plans.length ? plans.map(plan => `<article class="rc-plan"><div class="rc-plan-heading"><h3>${escape(plan.name)}</h3><strong>${escape(advice(plan))}</strong></div>
      <p>占用 ${plan.occupied} / ${plan.capacity_limit === null ? '未设销售上限' : plan.capacity_limit} · 主用节点容量 ${plan.primary_capacity} · 待分配订阅 ${plan.unassigned_subscribers}</p>
      <div class="rc-table-wrap"><table><thead><tr><th>节点 / 出口 IP</th><th>状态</th><th>已分配人数</th><th>订单预留</th><th>占用 / 容量</th><th>可分配空位</th></tr></thead><tbody>${plan.exits.map(exit => `<tr><td>${escape(exit.name)}<span class="rc-ip">${escape(exit.public_ip)}</span></td><td>${!exit.enabled ? '已停用' : exit.standby ? '备用 · ' + (exit.healthy ? '健康' : '不可用') : exit.healthy ? '健康' : '异常或检测过期'}</td><td>${exit.subscribers}</td><td>${exit.reserved}</td><td>${exit.occupied} / ${exit.capacity}</td><td>${exit.allocatable_slots}</td></tr>`).join('') || '<tr><td colspan="6">暂无出口节点</td></tr>'}</tbody></table></div></article>`).join('') : '<p class="rc-empty">尚未配置独享家宽套餐。</p>'}
      <p class="rc-help">有效订阅：未封禁、未到期（含永久）；流量耗尽仍计入。续费不重复计人。订单预留仅统计尚未计入有效分配的占用。节点空位不代表可售，当前可新增还受健康、备用状态、套餐销售上限和停售限制。</p>
      ${data.shared_nodes.length ? `<details class="rc-shared" open><summary>普通套餐共享家宽节点 · ${data.shared_nodes.length} 个</summary><p>按当前节点的套餐权限统计有效订阅。同一用户可能有多个节点权限，各行不能相加；此人数不代表在线人数或独享名额。</p><ul>${data.shared_nodes.map(node => `<li><span>${escape(node.name)}</span><strong>${node.subscribers} 人有使用权限</strong></li>`).join('')}</ul></details>` : ''}`;
  }
  async function load() {
    if (!panel || request) return;
    const target = panel, current = auth, controller = new AbortController(); request = controller;
    const status = target.querySelector('.rc-status'), button = target.querySelector('button');
    button.disabled = true; status.textContent = '正在读取订阅与容量…';
    const timer = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch('/api/v2/' + encodeURIComponent(path) + '/stat/getResidentialCapacity', {
        headers: {Authorization: current, Accept: 'application/json'}, cache: 'no-store', credentials: 'same-origin', signal: controller.signal,
      });
      if (!response.ok) throw new Error(response.status === 403 ? '登录已失效或没有管理员权限，请重新登录。' : '加载失败，请重试。');
      const {data} = await response.json();
      if (panel !== target || auth !== current || token() !== current || !home()) return;
      render(data, target); status.textContent = ''; nextRefresh = Date.now() + 60000;
    } catch (error) {
      if (panel !== target || auth !== current) return;
      // Never leave old capacity numbers looking current after an unsuccessful refresh.
      target.querySelector('.rc-data').replaceChildren(); target.querySelector('.rc-time').textContent = '';
      status.textContent = error.name === 'AbortError' ? '读取超时，请重试。' : error.message;
      nextRefresh = Date.now() + 60000;
    } finally {
      clearTimeout(timer);
      if (request === controller) request = null;
      if (panel === target) button.disabled = false;
    }
  }
  function mount() {
    const current = token();
    if (auth !== current) { remove(); auth = current; }
    if (!current || !home() || !document.querySelector('nav a[href="#/"]')) { remove(); return; }
    if (panel?.isConnected) {
      if (!document.hidden && Date.now() >= nextRefresh) load();
      return;
    }
    const host = document.querySelector('main > div > div.flex-1');
    if (!host) return;
    remove(); panel = document.createElement('section'); panel.id = 'residential-capacity'; panel.setAttribute('aria-label', '家宽订阅与容量');
    panel.innerHTML = '<div class="rc-heading"><div><h2>家宽订阅与容量</h2><span class="rc-time"></span></div><button type="button">刷新</button></div><p class="rc-status" role="status" aria-live="polite"></p><div class="rc-data"></div>';
    panel.querySelector('button').addEventListener('click', load); host.prepend(panel); load();
  }
  addEventListener('hashchange', mount); addEventListener('storage', mount);
  setInterval(mount, 1000); mount();
})();

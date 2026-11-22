(() => {
  'use strict';
  const path = document.body.dataset.adminPath;
  if (!path) return;
  const pageHash = '#/?page=residential-capacity';
  const activeClasses = ['bg-secondary', 'text-secondary-foreground', 'shadow-sm', 'hover:bg-secondary/80'];
  const initialTitle = document.title;
  let panel, host, heading, title, request, auth = '', nextRefresh = 0;
  const token = () => {
    try {
      const stored = JSON.parse(localStorage.getItem('XBOARD_ACCESS_TOKEN'));
      return stored && (!stored.expire || stored.expire > Date.now()) ? stored.value : '';
    } catch { return ''; }
  };
  const route = () => {
    const [pathname, search = ''] = location.hash.slice(1).split('?');
    return (!pathname || pathname === '/') && new URLSearchParams(search).get('page') === 'residential-capacity';
  };
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function remove() {
    request?.abort(); request = null;
    panel?.remove(); title?.remove();
    host?.classList.remove('rc-page-host'); heading?.parentElement?.classList.remove('rc-page-heading');
    document.body.classList.remove('rc-page-active');
    if (document.title === '家宽订阅与容量 · ' + initialTitle) document.title = initialTitle;
    panel = host = heading = title = null; nextRefresh = 0;
  }
  function advice(plan) {
    if (!plan.selling) return '套餐已停售';
    if (plan.capacity_limit !== null && plan.occupied >= plan.capacity_limit) return '套餐销售上限已满';
    if (!plan.primary_capacity) return '暂无主用出口，请补充节点';
    if (!plan.available_slots) return plan.exits.some(e => e.enabled && !e.standby && e.free_slots > 0)
      ? '有空位的节点暂不可用，请检查健康状态' : '主用出口已满，请补充节点';
    return `当前还可新增 ${plan.available_slots} 个订阅`;
  }
  function statCards(items) {
    return `<div class="rc-stats">${items.map(([label, count, unit]) => `<div><span>${label}</span><strong>${escape(count)}<small> ${unit}</small></strong></div>`).join('')}</div>`;
  }
  function renderProxy(inventory) {
    const {hosts, buyers, totals} = inventory;
    if (!hosts.length) return '<p class="rc-empty">尚未配置家宽代理主机。</p>';
    const stats = statCards([
      ['有效买家', buyers, '人'], ['有效订阅', totals.active, '个端口'],
      ['新购预留', totals.reserved, '个端口'], ['当前可售', totals.available, '个端口'],
    ]);
    const states = {online: '在线', stale: '心跳过期', disabled: '已停用'};
    const enrollmentNames = {registered:'待安装', installed:'待验收', testing:'验收中', draining:'正在撤回测试授权', failed:'验收失败', timeout:'验收超时'};
    const errors = {direct:'直连协议或出口 IP 未通过', route:'第一阶段线路未通过', auth:'错误凭据检查未通过', timeout:'连接超时'};
    const action = host => {
      if (host.enrollment === 'registered') return '<button type="button" data-action="command" data-id="'+Number(host.id)+'">生成安装命令</button>';
      if (['installed','failed','timeout'].includes(host.enrollment)) return '<button type="button" data-action="accept" data-id="'+Number(host.id)+'">验收并上架</button>';
      return '';
    };
    const rows = hosts.map(host => `<tr>
      <td>${escape(host.label || host.address)}${host.label ? '<span class="rc-ip">'+escape(host.country)+' · '+escape(host.address)+'</span>' : ''}</td><td>${enrollmentNames[host.enrollment] || states[host.status]}${host.probe_error ? '<span class="rc-ip">'+escape(errors[host.probe_error])+'</span>' : ''}<span class="rc-ip">${host.seen_at ? '心跳 ' + new Date(host.seen_at * 1000).toLocaleString() : '暂无心跳'}</span></td>
      <td><strong>${host.available}</strong> / ${host.ports}</td><td>${host.active}</td><td>${host.reserved}</td>
      <td>${host.expired}</td><td>${host.restricted}</td><td>${host.unavailable}</td><td>${action(host)}</td></tr>`).join('');
    return `${stats}<div class="rc-plan"><div class="rc-plan-heading"><h3>按出口 IP 查看端口</h3><strong>${hosts.length} 个出口 · 共 ${totals.ports} 个端口</strong></div>
      <div class="rc-table-wrap"><table><thead><tr><th>出口 IP</th><th>主机状态</th><th>可售 / 总端口</th><th>有效订阅</th><th>新购预留</th><th>到期保留</th><th>账号受限</th><th>不可售空位</th><th>操作</th></tr></thead><tbody>${rows}</tbody></table></div>
      <p class="rc-help">同一买家持有多个有效端口只计一人。续费沿用原端口，到期后仍保留归属。空闲端口仅在主机启用且最近 60 秒有心跳时可售。</p></div>`;
  }
  function renderDedicated(plans) {
    if (!plans.length) return '';
    const sum = key => plans.reduce((n, plan) => n + plan[key], 0);
    const stats = [['有效订阅', sum('subscribers'), '人'], ['已分配订阅', sum('assigned_subscribers'), '人'], ['订单预留', sum('reserved'), '个名额'], ['当前可新增', sum('available_slots'), '个名额']];
    return `
      <h2 class="rc-section-title">独享家宽套餐</h2>
      ${statCards(stats)}
      ${plans.map(plan => `<article class="rc-plan"><div class="rc-plan-heading"><h3>${escape(plan.name)}</h3><strong>${escape(advice(plan))}</strong></div>
      <p>占用 ${plan.occupied} / ${plan.capacity_limit === null ? '未设销售上限' : plan.capacity_limit} · 主用节点容量 ${plan.primary_capacity} · 待分配订阅 ${plan.unassigned_subscribers}</p>
      <div class="rc-table-wrap"><table><thead><tr><th>节点 / 出口 IP</th><th>状态</th><th>已分配人数</th><th>订单预留</th><th>占用 / 容量</th><th>可分配空位</th></tr></thead><tbody>${plan.exits.map(exit => `<tr><td>${escape(exit.name)}<span class="rc-ip">${escape(exit.public_ip)}</span></td><td>${!exit.enabled ? '已停用' : exit.standby ? '备用 · ' + (exit.healthy ? '健康' : '不可用') : exit.healthy ? '健康' : '异常或检测过期'}</td><td>${exit.subscribers}</td><td>${exit.reserved}</td><td>${exit.occupied} / ${exit.capacity}</td><td>${exit.allocatable_slots}</td></tr>`).join('') || '<tr><td colspan="6">暂无出口节点</td></tr>'}</tbody></table></div></article>`).join('')}
      <p class="rc-help">有效订阅：未封禁、未到期（含永久）；流量耗尽仍计入。续费不重复计人。订单预留仅统计尚未计入有效分配的占用。节点空位不代表可售，当前可新增还受健康、备用状态、套餐销售上限和停售限制。</p>`;
  }
  function render(data, target) {
    target.querySelector('.rc-time').textContent = '更新于 ' + new Date(data.checked_at * 1000).toLocaleTimeString();
    target.querySelector('.rc-data').innerHTML = `
      ${renderProxy(data.proxy_inventory)}
      ${renderDedicated(data.plans)}
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
      if (panel !== target || auth !== current || token() !== current || !route()) return;
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
  function bindEnrollment(target) {
    const dialog = target.querySelector('.rc-enroll');
    const form = dialog.querySelector('form');
    const commandBox = dialog.querySelector('textarea');
    const output = dialog.querySelector('.rc-message');
    const fields = dialog.querySelector('fieldset');
    const submit = dialog.querySelector('[type=submit]');
    const copy = dialog.querySelector('.rc-copy');
    let busy = false;
    const clear = () => { commandBox.value = ''; output.textContent = ''; copy.hidden = commandBox.hidden = true; };
    const open = register => {
      clear(); fields.hidden = submit.hidden = !register;
      dialog.querySelector('h3').textContent = register ? '添加家宽出口' : '出口部署';
      dialog.showModal();
    };
    async function send(action, body) {
      if (busy) return;
      busy = true; submit.disabled = true;
      const current = auth;
      try {
        const response = await fetch('/api/v2/'+encodeURIComponent(path)+'/stat/residential/'+action, {
          method:'POST', headers:{Authorization:current, Accept:'application/json','Content-Type':'application/json'},
          body:JSON.stringify(body), credentials:'same-origin', cache:'no-store',
        });
        const result = await response.json();
        if (panel !== target || auth !== current || token() !== current || !dialog.open) return;
        if (!response.ok) throw new Error(result.message || '操作失败，请重试。');
        fields.hidden = submit.hidden = true;
        if (result.data?.command) {
          commandBox.hidden = copy.hidden = false; commandBox.value = result.data.command;
          output.textContent = '在新 VPS 执行此命令（30 分钟内有效）。安装完成后，返回出口行点击「验收并上架」。';
        } else {
          output.textContent = '已开始验收。通过两种协议和第一阶段检查、撤回测试授权后会自动上架。';
        }
        nextRefresh = 0; void load();
      } catch (error) { if (panel === target && dialog.open) output.textContent = error.message; }
      finally { busy = false; submit.disabled = false; }
    }
    target.querySelector('.rc-add').addEventListener('click', () => { form.reset(); open(true); });
    dialog.querySelector('.rc-close').addEventListener('click', () => dialog.close());
    dialog.addEventListener('close', clear);
    copy.addEventListener('click', async () => {
      try { await navigator.clipboard.writeText(commandBox.value); output.textContent = '安装命令已复制。'; }
      catch { commandBox.select(); output.textContent = '请复制已选中的安装命令。'; }
    });
    form.addEventListener('submit', event => {
      event.preventDefault();
      void send('register', Object.fromEntries(new FormData(form)));
    });
    target.querySelector('.rc-data').addEventListener('click', event => {
      const button = event.target.closest('button[data-action]'); if (!button || busy) return;
      open(false); output.textContent = '正在提交…';
      void send(button.dataset.action, {id:Number(button.dataset.id)});
    });
  }
  function mount() {
    const current = token();
    if (auth !== current) { remove(); auth = current; }
    const homeLink = document.querySelector('nav a[href="#/"]');
    let nav = document.getElementById('residential-capacity-nav');
    if (!current || !homeLink || location.hash.startsWith('#/sign-in')) { remove(); nav?.remove(); return; }
    if (!nav) {
      nav = document.createElement('a'); nav.id = 'residential-capacity-nav'; nav.href = pageHash;
      nav.setAttribute('aria-label', '家宽订阅与容量'); nav.title = '家宽订阅与容量';
      nav.innerHTML = '<div class="mr-2"><svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1z"/><path d="M9 21v-8h6v8"/></svg></div><span>家宽订阅与容量</span>';
      nav.addEventListener('click', event => {
        if (event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) {
          document.querySelector('button[aria-controls="sidebar-menu"][aria-expanded="true"]')?.click();
        }
      });
      (document.getElementById('node-probe-nav') || homeLink).after(nav);
    }
    const active = route();
    nav.className = homeLink.className.split(' ').filter(c => !activeClasses.includes(c)).join(' ') + (active ? ' ' + activeClasses.join(' ') : ' hover:bg-accent');
    if (active) { nav.setAttribute('aria-current', 'page'); homeLink.removeAttribute('aria-current'); }
    else { nav.removeAttribute('aria-current'); if (['', '#', '#/'].includes(location.hash)) homeLink.setAttribute('aria-current', 'page'); }
    if (!active) { remove(); return; }
    if (panel?.isConnected) {
      if (!document.hidden && Date.now() >= nextRefresh) load();
      return;
    }
    const content = document.querySelector('main > div > div.flex-1');
    const originalHeading = document.querySelector('main h1:not(#node-quality-title):not(#residential-capacity-title)');
    if (!content || !originalHeading) return;
    remove(); host = content; heading = originalHeading;
    title = document.createElement('h1'); title.id = 'residential-capacity-title'; title.className = heading.className; title.textContent = '家宽订阅与容量';
    heading.parentElement.append(title); heading.parentElement.classList.add('rc-page-heading');
    panel = document.createElement('section'); panel.id = 'residential-capacity'; panel.setAttribute('aria-label', '家宽订阅与容量');
    panel.innerHTML = '<div class="rc-heading"><div><h2>家宽代理</h2><span class="rc-time"></span></div><div><button type="button">刷新</button> <button type="button" class="rc-add">添加家宽出口</button></div></div><p class="rc-status" role="status" aria-live="polite"></p><div class="rc-data"></div>';
    panel.innerHTML += `<dialog class="rc-enroll"><div class="rc-heading"><h3>添加家宽出口</h3><button type="button" class="rc-close">关闭</button></div>
      <form><fieldset><label>出口名称<input name="label" required maxlength="80" placeholder="英国家宽 01"></label>
      <label>地区<input name="country" required maxlength="40" placeholder="英国"></label>
      <label>固定公网 IPv4<input name="address" required placeholder="填写出口公网地址"></label>
      <p>每台提供 10 个 TCP 端口（20001–20010），每端口 100 Mbps。安装器支持 Debian / Ubuntu x86_64。</p></fieldset>
      <button type="submit">登记并生成安装命令</button></form><p class="rc-message" role="status"></p>
      <textarea readonly hidden aria-label="安装命令"></textarea><button type="button" class="rc-copy" hidden>复制命令</button></dialog>`;
    bindEnrollment(panel);
    panel.querySelector('button').addEventListener('click', load); host.append(panel);
    host.classList.add('rc-page-host'); document.body.classList.add('rc-page-active'); host.scrollTop = 0;
    document.title = '家宽订阅与容量 · ' + initialTitle; load();
  }
  const root = document.getElementById('root');
  if (root) new MutationObserver(mount).observe(root, {childList: true, subtree: true});
  addEventListener('hashchange', mount); addEventListener('storage', mount);
  setInterval(mount, 1000); mount();
})();

(function () {
  'use strict';
  var id = new URLSearchParams(location.hash.slice(1)).get('request_id') || '';
  var valid = /^[0-9A-HJKMNP-TV-Z]{26}$/.test(id);
  // Browsers may reuse an existing tab and only change the fragment for a new attempt.
  addEventListener('hashchange', function () { location.reload(); });
  var pendingKey = 'capybara-desktop-login';
  var context, selectedToken = '', running = false;
  var el = function (name) { return document.getElementById(name); };
  function token() {
    try {
      var item = JSON.parse(localStorage.getItem('VUE_NAIVE_ACCESS_TOKEN') || 'null');
      return item && item.value && (!item.expire || item.expire > Date.now()) ? String(item.value) : '';
    } catch (_) { return ''; }
  }
  function show(message, buttons) {
    el('message').textContent = message;
    ['approve', 'login', 'reject', 'retry'].forEach(function (name) { el(name).hidden = buttons.indexOf(name) === -1; });
  }
  async function api(path, auth, body) {
    var headers = { Accept: 'application/json' };
    if (auth) headers.Authorization = auth;
    if (body) headers['Content-Type'] = 'application/json';
    var controller = new AbortController();
    var timer = setTimeout(function () { controller.abort(); }, 15000);
    try {
      var response = await fetch('/api/v1/' + path, {
        method: body ? 'POST' : 'GET', headers: headers, body: body ? JSON.stringify(body) : undefined,
        cache: 'no-store', credentials: 'same-origin', redirect: 'error', signal: controller.signal
      });
      var value = await response.json();
      if (!response.ok) {
        var error = new Error(response.status === 410 ? '本次授权已结束，请返回客户端重新登录。' :
          response.status === 401 || response.status === 403 ? '网页登录已失效或账号无法授权，请重新登录。' :
          response.status === 409 ? '本次请求已由其他账号处理，请返回客户端重新登录。' :
          response.status === 429 ? '操作过于频繁，请稍后重试。' : '账户服务暂时不可用，请稍后重试。');
        error.status = response.status;
        throw error;
      }
      return value.data;
    } catch (e) {
      if (e.status) throw e;
      throw new Error('暂时无法连接账户服务，请检查网络后重试。');
    } finally { clearTimeout(timer); }
  }
  async function load() {
    if (running) return;
    running = true;
    el('details').hidden = true;
    show('正在检查授权请求…', []);
    try {
      if (!valid) { show('授权链接无效，请从卡皮巴拉客户端点击登录。', []); return; }
      context = await api('auth/browser/context?request_id=' + id);
      selectedToken = token();
      if (!selectedToken) { show('登录官网后即可授权客户端使用你的账号。', ['login']); return; }
      var user;
      try { user = await api('user/info', selectedToken); }
      catch (e) {
        if (e.status === 401 || e.status === 403) { show(e.message, ['login']); return; }
        throw e;
      }
      if (!user || typeof user.email !== 'string') throw new Error('无法确认当前账号，请重新登录官网。');
      el('account').textContent = user.email;
      el('device').textContent = context.device_name + ' · ' + context.platform;
      el('details').hidden = false;
      show('确认使用以下账号登录你刚刚打开的客户端。', ['approve', 'reject']);
    } catch (e) { show(e.message, e.status === 410 || e.status === 409 ? [] : ['retry']); }
    finally { running = false; }
  }
  el('login').onclick = function () {
    try {
      sessionStorage.setItem(pendingKey, JSON.stringify({ request_id: id, expires_at: Date.parse(context.expires_at) }));
      location.assign('/#/login');
    } catch (_) { show('浏览器存储不可用，请允许本站存储后重试。', ['retry']); }
  };
  async function decide(approved) {
    if (running) return;
    // Never silently approve with a different account than the one displayed.
    if (token() !== selectedToken) { await load(); return; }
    running = true;
    ['approve', 'reject'].forEach(function (name) { el(name).disabled = true; });
    try {
      await api('auth/browser/approve', selectedToken, { request_id: id, approved: approved });
      sessionStorage.removeItem(pendingKey);
      el('details').hidden = true;
      show(approved ? '授权完成，请返回卡皮巴拉客户端。此页面可以关闭。' : '已取消授权，可以关闭此页面。', []);
    } catch (e) {
      show(e.message, e.status === 410 || e.status === 409 ? [] : ['retry']);
    } finally {
      running = false;
      ['approve', 'reject'].forEach(function (name) { el(name).disabled = false; });
    }
  }
  el('approve').onclick = function () { void decide(true); };
  el('reject').onclick = function () { void decide(false); };
  el('retry').onclick = function () { void load(); };
  void load();
}());

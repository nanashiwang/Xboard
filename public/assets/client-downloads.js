(function () {
  'use strict';
  var key = 'VUE_NAIVE_ACCESS_TOKEN';
  var sections = Array.from(document.querySelectorAll('.client'));
  var tabs = Array.from(document.querySelectorAll('[data-platform]'));
  var currentToken = '';
  var generation = 0;
  var controller;
  var authenticatedSections = new WeakMap();

  function syncTheme() {
    try {
      var preference = localStorage.getItem('vueuse-color-scheme');
      document.documentElement.dataset.theme = preference === 'dark' || preference === 'light' ? preference : 'auto';
    } catch (_) { /* System color scheme remains available without storage. */ }
  }

  function token() {
    try {
      var value = JSON.parse(localStorage.getItem(key) || 'null');
      return value && value.value && (!value.expire || value.expire > Date.now()) ? String(value.value) : '';
    } catch (_) { return ''; }
  }

  function device() {
    var ua = navigator.userAgent;
    if (/iPad|iPhone|iPod/i.test(ua) || (/Macintosh/i.test(ua) && navigator.maxTouchPoints > 1)) return 'ios';
    if (/Android/i.test(ua)) return 'android';
    if (/Win/i.test(ua)) return 'windows';
    if (/Mac/i.test(ua)) return 'macos';
    if (/Linux/i.test(ua)) return 'linux';
    return 'windows';
  }

  function message(section, text, error) {
    var status = section.querySelector('.status');
    status.textContent = text;
    status.classList.toggle('error', !!error);
  }

  function clear() {
    generation++;
    if (controller) controller.abort();
    sections.forEach(function (section) {
      section.querySelector('.auth-state').hidden = !!currentToken;
      section.querySelector('.import-controls').hidden = !currentToken;
      section.querySelector('.import-ready').hidden = true;
      section.querySelector('.launch').removeAttribute('href');
      section.querySelector('.subscription').value = '';
      section.querySelector('.manual').open = false;
      section.querySelector('.prepare').hidden = false;
      section.querySelector('.prepare').disabled = false;
      section.querySelector('.prepare').textContent = '获取我的订阅';
      authenticatedSections.delete(section);
      message(section, '');
    });
  }

  function active() { return sections.find(function (section) { return !section.hidden; }); }

  function syncAuth() {
    var next = token();
    if (next !== currentToken) {
      currentToken = next;
      clear();
      if (next && active()) prepare(active());
    }
  }

  async function prepare(section) {
    syncAuth();
    if (!currentToken || section.querySelector('.prepare').disabled) return;
    if (controller) controller.abort();
    controller = new AbortController();
    var request = controller;
    var attempt = ++generation;
    var auth = currentToken;
    var button = section.querySelector('.prepare');
    button.disabled = true;
    button.textContent = '正在获取订阅…';
    message(section, '');
    var timer = setTimeout(function () { request.abort(); }, 15000);
    try {
      var response = await fetch('/api/v1/user/client/import?client=' + encodeURIComponent(section.dataset.client), {
        headers: { Authorization: auth, Accept: 'application/json' },
        signal: request.signal, cache: 'no-store', credentials: 'same-origin'
      });
      var payload;
      try { payload = await response.json(); }
      catch (_) { throw new Error('服务器未返回有效数据，请稍后重试。'); }
      if (!response.ok) throw new Error(payload.message || '获取订阅失败，请稍后重试。');
      if (attempt !== generation || auth !== token()) return;
      var data = payload.data || {};
      var schemes = { 'clash-verge': 'clash-verge:', 'clash-meta': 'clashmeta:', 'sing-box': 'sing-box:' };
      if (!/^https?:\/\//i.test(data.subscribe_url || '') || !String(data.import_url || '').startsWith(schemes[section.dataset.client])) {
        throw new Error('订阅地址格式异常，请联系管理员。');
      }
      section.querySelector('.launch').href = data.import_url;
      section.querySelector('.subscription').value = data.subscribe_url;
      authenticatedSections.set(section, auth);
      section.querySelector('.import-ready').hidden = false;
      button.hidden = true;
    } catch (error) {
      if (attempt !== generation || auth !== token()) return;
      message(section, error.name === 'AbortError' ? '请求超时，请检查网络后重试。' : error instanceof TypeError ? '网络连接失败，请检查网络后重试。' : error.message, true);
      button.textContent = '重新获取订阅';
    } finally {
      clearTimeout(timer);
      if (attempt === generation) button.disabled = false;
    }
  }

  function select() {
    var platform = location.hash.slice(1);
    if (!sections.some(function (section) { return section.id === platform; })) platform = device();
    sections.forEach(function (section) { section.hidden = section.id !== platform; });
    tabs.forEach(function (tab) { tab.setAttribute('aria-current', String(tab.dataset.platform === platform)); });
    var tab = tabs.find(function (item) { return item.dataset.platform === platform; });
    document.getElementById('device-hint').textContent = platform === device()
      ? '已按当前设备推荐 ' + tab.textContent + '，也可以切换到其他设备。'
      : '正在查看 ' + tab.textContent + ' 的安装方式。';
    clear();
    if (currentToken) prepare(active());
  }

  sections.forEach(function (section) {
    section.querySelector('.prepare').addEventListener('click', function () { prepare(section); });
    section.querySelector('.launch').addEventListener('click', function (event) {
      if (!token() || token() !== authenticatedSections.get(section)) {
        event.preventDefault(); syncAuth(); return;
      }
      message(section, '请在浏览器提示中允许打开客户端，然后在客户端确认导入。');
    });
    section.querySelector('.copy').addEventListener('click', async function () {
      if (!token() || token() !== authenticatedSections.get(section)) { syncAuth(); return; }
      var input = section.querySelector('.subscription');
      try {
        await navigator.clipboard.writeText(input.value);
        message(section, '已复制，可在客户端中添加远程订阅。');
      } catch (_) {
        section.querySelector('.manual').open = true;
        input.focus(); input.select();
        message(section, '浏览器未允许自动复制，请复制下方已选中的地址。');
      }
    });
  });
  tabs.forEach(function (tab) {
    tab.addEventListener('click', function (event) {
      event.preventDefault();
      history.replaceState(null, '', '#' + tab.dataset.platform);
      select();
    });
  });
  window.addEventListener('hashchange', select);
  window.addEventListener('storage', syncAuth);
  window.addEventListener('storage', syncTheme);
  window.addEventListener('pageshow', function (event) {
    if (event.persisted) { currentToken = token(); select(); } else syncAuth();
  });
  document.addEventListener('visibilitychange', function () { if (!document.hidden) syncAuth(); });
  currentToken = token();
  syncTheme();
  select();
})();

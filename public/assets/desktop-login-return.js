(function () {
  'use strict';
  var key = 'capybara-desktop-login', pending;
  try { pending = JSON.parse(sessionStorage.getItem(key) || 'null'); } catch (_) { return; }
  if (!pending) return;
  if (!/^[0-9A-HJKMNP-TV-Z]{26}$/.test(pending.request_id) ||
      !Number.isFinite(pending.expires_at) || pending.expires_at <= Date.now() || pending.expires_at > Date.now() + 300000) {
    sessionStorage.removeItem(key); return;
  }
  var running = false, last = '', retryAfter = 0;
  async function check() {
    if (running) return;
    if (Date.now() >= pending.expires_at) { sessionStorage.removeItem(key); clearInterval(timer); return; }
    var token = '';
    try {
      var item = JSON.parse(localStorage.getItem('VUE_NAIVE_ACCESS_TOKEN') || 'null');
      if (item && item.value && (!item.expire || item.expire > Date.now())) token = String(item.value);
    } catch (_) { return; }
    if (!token || token === last || Date.now() < retryAfter) return;
    running = true;
    var controller = new AbortController();
    var timeout = setTimeout(function () { controller.abort(); }, 10000);
    try {
      var response = await fetch('/api/v1/user/checkLogin', {
        headers: { Accept: 'application/json', Authorization: token },
        credentials: 'same-origin', cache: 'no-store', redirect: 'error', signal: controller.signal
      });
      if (response.status === 401 || response.status === 403) { last = token; return; }
      if (!response.ok) { retryAfter = Date.now() + 5000; return; }
      var body = await response.json();
      if (body.data && body.data.is_login && Date.now() < pending.expires_at) {
        sessionStorage.removeItem(key); clearInterval(timer);
        location.replace('/desktop/login#request_id=' + pending.request_id);
      } else { last = token; }
    } catch (_) { retryAfter = Date.now() + 5000; }
    finally { clearTimeout(timeout); running = false; }
  }
  var timer = setInterval(check, 500);
  addEventListener('pagehide', function () { clearInterval(timer); }, { once: true });
  void check();
}());

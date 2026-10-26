import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { JSDOM } from 'jsdom';

const root = new URL('../../../', import.meta.url);
const id = '01K8ABCDEFGHJKMNPQRSTVWXYZ';
const storage = () => {
  const data = new Map();
  return { getItem: (k) => data.get(k) ?? null, setItem: (k, v) => data.set(k, v), removeItem: (k) => data.delete(k) };
};
const settle = () => new Promise((resolve) => setImmediate(resolve));
function harness(script, replies = [], login = '') {
  const dom = new JSDOM(readFileSync(new URL('resources/views/client/browser-login.blade.php', root), 'utf8'));
  const localStorage = storage(), sessionStorage = storage(), calls = [], redirects = [], navigation = [];
  if (login) localStorage.setItem('VUE_NAIVE_ACCESS_TOKEN', JSON.stringify({ value: login }));
  const intervals = [], events = {}, timeouts = new Map();
  let nextTimer = 0;
  const window = { closed: false, closeCalls: 0, close() { this.closeCalls++; this.closed = true; } };
  const context = {
    document: dom.window.document, location: { hash: '#request_id=' + id, assign: (url) => { navigation.push('assign'); redirects.push(url); }, replace: (url) => { navigation.push('replace'); redirects.push(url); }, reload: () => redirects.push('reload') },
    localStorage, sessionStorage, URLSearchParams, AbortController, Date, window,
    setTimeout(fn) { timeouts.set(++nextTimer, fn); return nextTimer; }, clearTimeout(timer) { timeouts.delete(timer); },
    setInterval: (fn) => { intervals.push(fn); return intervals.length; }, clearInterval() {}, addEventListener(name, fn) { events[name] = fn; },
    async fetch(path, options) {
      calls.push({ path, options });
      const reply = await replies.shift();
      assert.ok(reply, 'unexpected API call: ' + path);
      return { ok: reply.status < 400, status: reply.status, json: async () => ({ data: reply.data }) };
    },
  };
  return { ...context, calls, redirects, navigation, intervals, events,
    flushTimeouts() { const pending = [...timeouts.values()]; timeouts.clear(); pending.forEach(fn => fn()); },
    run() { vm.runInNewContext(readFileSync(new URL('public/assets/' + script, root), 'utf8'), context); },
    el(name) { return context.document.getElementById(name); } };
}
const pending = () => ({ status: 200, data: { device_name: '测试电脑', platform: 'macos', expires_at: new Date(Date.now() + 240000).toISOString() } });

test('existing web login requires explicit approval; desktop tokens never enter browser', async () => {
  const h = harness('desktop-login.js', [pending(), { status: 200, data: { email: '<test>@example.invalid' } }, { status: 200, data: true }], 'Bearer web-only');
  h.run(); await settle();
  assert.equal(h.calls.length, 2);
  assert.equal(h.el('approve').hidden, false);
  assert.equal(h.el('account').textContent, '<test>@example.invalid');
  assert.equal(h.el('account').children.length, 0);
  h.el('approve').click(); await settle();
  assert.equal(h.calls[2].path, '/api/v1/auth/browser/approve');
  assert.deepEqual(JSON.parse(h.calls[2].options.body), { request_id: id, approved: true });
  assert.equal(h.calls[2].options.headers.Authorization, 'Bearer web-only');
  assert.match(h.el('message').textContent, /授权完成/);
  assert.equal(h.el('approve').hidden, true);
  assert.equal(h.window.closeCalls, 1);
  assert.deepEqual(h.redirects, []);
});
test('approval waits for server confirmation before closing, even if storage cleanup fails', async () => {
  let confirm;
  const h = harness('desktop-login.js', [pending(), { status: 200, data: { email: 'test@example.invalid' } },
    new Promise(resolve => { confirm = resolve; })], 'web-session');
  h.run(); await settle();
  h.sessionStorage.removeItem = () => { throw new Error('storage unavailable'); };
  h.el('approve').click(); await settle();
  assert.equal(h.window.closeCalls, 0);
  assert.equal(h.el('approve').disabled, true);
  confirm({ status: 200, data: true }); await settle();
  assert.equal(h.window.closeCalls, 1);
  assert.match(h.el('message').textContent, /授权完成/);
  assert.equal(h.el('retry').hidden, true);
});
test('blocked or throwing window.close keeps successful approval and offers no repeat approval', async () => {
  for (const throws of [false, true]) {
    const h = harness('desktop-login.js', [pending(), { status: 200, data: { email: 'test@example.invalid' } }, { status: 200, data: true }], 'web-session');
    h.window.close = () => { h.window.closeCalls++; if (throws) throw new Error('blocked'); };
    h.run(); await settle(); h.el('approve').click(); await settle(); h.flushTimeouts();
    assert.equal(h.window.closeCalls, 1);
    assert.equal(h.window.closed, false);
    assert.match(h.el('message').textContent, /授权完成。请关闭此标签页/);
    assert.equal(h.el('approve').hidden, true);
    assert.equal(h.el('retry').hidden, true);
    assert.equal(h.calls.length, 3);
  }
});
test('failed or unconfirmed approvals keep the page open for recovery', async () => {
  for (const reply of [{ status: 503 }, { status: 401 }, { status: 410 }, { status: 200, data: false }]) {
    const h = harness('desktop-login.js', [pending(), { status: 200, data: { email: 'test@example.invalid' } }, reply], 'web-session');
    h.run(); await settle(); h.el('approve').click(); await settle();
    assert.equal(h.window.closeCalls, 0);
    assert.doesNotMatch(h.el('message').textContent, /授权完成/);
  }
});
test('rejecting authorization does not close the page or report success', async () => {
  const h = harness('desktop-login.js', [pending(), { status: 200, data: { email: 'test@example.invalid' } }, { status: 200, data: true }], 'web-session');
  h.run(); await settle(); h.el('reject').click(); await settle();
  assert.deepEqual(JSON.parse(h.calls[2].options.body), { request_id: id, approved: false });
  assert.equal(h.window.closeCalls, 0);
  assert.match(h.el('message').textContent, /已取消授权/);
});
test('signed-out flow stores only request and expiry, then opens the existing website login', async () => {
  const h = harness('desktop-login.js', [pending()]); h.run(); await settle();
  assert.equal(h.el('login').hidden, false);
  h.el('login').click();
  const marker = JSON.parse(h.sessionStorage.getItem('capybara-desktop-login'));
  assert.deepEqual(Object.keys(marker).sort(), ['expires_at', 'request_id']);
  assert.equal(marker.request_id, id);
  assert.deepEqual(h.redirects, ['/#/login']);
  assert.deepEqual(h.navigation, ['replace']);
});
test('changing the web account requires a fresh confirmation', async () => {
  const h = harness('desktop-login.js', [pending(), { status: 200, data: { email: 'one@example.invalid' } }, pending(), { status: 200, data: { email: 'two@example.invalid' } }], 'first');
  h.run(); await settle();
  h.localStorage.setItem('VUE_NAIVE_ACCESS_TOKEN', JSON.stringify({ value: 'second' }));
  h.el('approve').click(); await settle();
  assert.equal(h.calls.filter((call) => call.options.method === 'POST').length, 0);
  assert.equal(h.window.closeCalls, 0);
  assert.equal(h.el('account').textContent, 'two@example.invalid');
});
test('expired or malformed requests cannot be approved', async () => {
  const h = harness('desktop-login.js', [{ status: 410 }], 'session'); h.run(); await settle();
  assert.match(h.el('message').textContent, /已结束/);
  assert.equal(h.el('approve').hidden, true);
  assert.equal(h.window.closeCalls, 0);
  const bad = harness('desktop-login.js'); bad.location.hash = '#request_id=https://evil.invalid'; bad.run(); await settle();
  assert.equal(bad.calls.length, 0);
  assert.match(bad.el('message').textContent, /链接无效/);
  assert.equal(bad.window.closeCalls, 0);
});
test('login return validates new session and only navigates to a fixed same-origin page', async () => {
  const h = harness('desktop-login-return.js', [{ status: 401 }, { status: 200, data: { is_login: true } }], 'expired');
  h.sessionStorage.setItem('capybara-desktop-login', JSON.stringify({ request_id: id, expires_at: Date.now() + 240000, redirect: 'https://evil.invalid' }));
  h.run(); await settle();
  assert.equal(h.redirects.length, 0);
  await h.intervals[0](); assert.equal(h.calls.length, 1);
  h.localStorage.setItem('VUE_NAIVE_ACCESS_TOKEN', JSON.stringify({ value: 'new-session' }));
  await h.intervals[0]();
  assert.deepEqual(h.redirects, ['/desktop/login#request_id=' + id]);
  assert.equal(h.sessionStorage.getItem('capybara-desktop-login'), null);
});
test('expired return markers cannot redirect or send credentials', () => {
  const h = harness('desktop-login-return.js', [], 'session');
  h.sessionStorage.setItem('capybara-desktop-login', JSON.stringify({ request_id: id, expires_at: Date.now() - 1 }));
  h.run();
  assert.equal(h.calls.length, 0); assert.equal(h.redirects.length, 0);
  assert.equal(h.sessionStorage.getItem('capybara-desktop-login'), null);
});
test('reusing a browser tab for another request resets the previous authorization UI', async () => {
  const h = harness('desktop-login.js', [pending()]); h.run(); await settle();
  h.location.hash = '#request_id=01K8ABCDEFGHJKMNPQRSTVWXY0';
  h.events.hashchange();
  assert.deepEqual(h.redirects, ['reload']);
});


test('registration intent opens the official registration form with the same bounded return marker', async () => {
  const h = harness('desktop-login.js', [pending()]);
  h.location.hash += '&flow=register&redirect=https://evil.invalid';
  h.run(); await settle();
  assert.deepEqual(h.redirects, ['/#/register']);
  const marker = JSON.parse(h.sessionStorage.getItem('capybara-desktop-login'));
  assert.deepEqual(Object.keys(marker).sort(), ['expires_at', 'request_id']);
  assert.equal(marker.request_id, id);
  assert.equal(h.calls.filter(call => call.options.method === 'POST').length, 0);
});
test('website authorization offers registration and never silently replaces an existing web account', async () => {
  const h = harness('desktop-login.js', [pending()]); h.run(); await settle();
  assert.equal(h.el('register').hidden, false);
  h.el('register').click();
  assert.deepEqual(h.redirects, ['/#/register']);
  const logged = harness('desktop-login.js', [pending(), { status: 200, data: { email: 'existing@example.invalid' } }], 'existing-web-token');
  logged.location.hash += '&flow=register'; logged.run(); await settle();
  assert.deepEqual(logged.redirects, []);
  assert.equal(logged.el('approve').hidden, false);
  assert.match(logged.el('message').textContent, /官网已登录/);
  assert.equal(logged.calls.filter(call => call.options.method === 'POST').length, 0);
});
test('newly registered website session returns to explicit authorization without exposing its token', async () => {
  const h = harness('desktop-login-return.js', [{ status: 200, data: { is_login: true } }]);
  h.location.hash = '#/register';
  h.sessionStorage.setItem('capybara-desktop-login', JSON.stringify({ request_id: id, expires_at: Date.now() + 240000 }));
  h.run(); await settle(); assert.equal(h.calls.length, 0);
  h.localStorage.setItem('VUE_NAIVE_ACCESS_TOKEN', JSON.stringify({ value: 'new-registration-session' }));
  await h.intervals[0]();
  assert.deepEqual(h.redirects, ['/desktop/login#request_id=' + id]);
  assert.equal(h.sessionStorage.getItem('capybara-desktop-login'), null);
});

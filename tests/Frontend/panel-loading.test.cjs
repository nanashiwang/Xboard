const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('public/assets/capybara-home/panel-loading.js', 'utf8');
function boot(hash = '#/login') {
  const handlers = {}, timers = new Map(); let current = 0, reloads = 0, mounted = false, observe;
  const loader = { hidden: false }, message = {}, retry = {};
  const app = { querySelector: () => mounted ? {} : null };
  retry.addEventListener = (name, cb) => { retry[name] = cb; };
  const nodes = { 'capy-panel-loading': loader, 'capy-panel-loading-message': message, 'capy-panel-retry': retry, app };
  const location = { hash, reload: () => reloads++ };
  let disconnected = false;
  vm.runInNewContext(source, { document: { getElementById: id => nodes[id] }, location,
    window: { addEventListener: (name, cb) => { handlers[name] = cb; } },
    setTimeout: cb => { timers.set(++current, cb); return current; }, clearTimeout: id => timers.delete(id),
    MutationObserver: class { constructor(cb) { observe = cb; } observe() {} disconnect() { disconnected = true; } },
  });
  return { loader, message, timers, location, handlers, get reloads() { return reloads; }, get disconnected() { return disconnected; },
    mount() { mounted = true; observe(); }, retry() { let prevented = false; retry.click({ preventDefault() { prevented = true; } }); return prevented; },
    timeout() { [...timers.values()].forEach(cb => cb()); },
  };
}
test('loading stays visible until real panel controls mount, then clears timeout', () => {
  const s = boot(); assert.equal(s.loader.hidden, false); assert.equal(s.timers.size, 1);
  s.mount(); assert.equal(s.loader.hidden, true); assert.equal(s.timers.size, 0); assert.equal(s.disconnected, true);
});
test('slow load can still succeed after the waiting message', () => {
  const s = boot(); s.timeout(); assert.match(s.message.textContent, /加载时间有点长/); s.mount(); assert.equal(s.loader.hidden, true);
});
test('network failure shows recovery and retry preserves current hash', () => {
  const s = boot('#/register'); s.handlers['xboard:panel-error'](); assert.match(s.message.textContent, /页面加载失败/);
  assert.equal(s.timers.size, 0); assert.equal(s.retry(), true); assert.equal(s.reloads, 1); assert.equal(s.location.hash, '#/register');
});
test('homepage does not start waiting timer, but a later panel transition does', () => {
  const s = boot(''); assert.equal(s.timers.size, 0); s.location.hash = '#/login'; s.handlers.hashchange(); assert.equal(s.timers.size, 1);
});

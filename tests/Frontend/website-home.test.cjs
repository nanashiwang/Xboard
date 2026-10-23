const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../../public/assets/capybara-home/home.js'), 'utf8');

function boot({ headMode, hash }) {
  const handlers = {};
  const scripts = [];
  let reloads = 0;
  const element = () => ({ hidden: true, setAttribute() {}, addEventListener() {}, classList: { remove() {} } });
  const menu = element();
  const navigation = element();
  const root = { ...element(), querySelector: selector => selector === '.capy-menu' ? menu : navigation };
  const document = {
    documentElement: { dataset: { xboardPage: headMode } },
    currentScript: { dataset: { panelSrc: '/theme/Xboard/assets/umi.js' } },
    head: { appendChild: script => scripts.push(script) },
    body: { appendChild: script => scripts.push(script) },
    createElement: () => ({}),
    querySelector: () => root,
    addEventListener() {},
  };
  const location = { hash, reload: () => reloads++ };
  const window = {
    settings: { assets_path: '/theme/Xboard/assets', version: 'test' },
    addEventListener: (name, handler, capture) => { handlers[name] = { handler, capture }; },
  };
  vm.runInNewContext(source, { document, window, location, encodeURIComponent });
  return {
    document, scripts, location,
    get reloads() { return reloads; },
    fire(name, fields = {}) {
      const event = { ...fields, stopped: false, stopImmediatePropagation() { this.stopped = true; } };
      handlers[name].handler(event);
      return { stopped: event.stopped, capture: handlers[name].capture };
    },
  };
}

test('clicking register before the deferred loader arrives reveals the panel', () => {
  const state = boot({ headMode: 'home', hash: '#/register' });
  assert.equal(state.document.documentElement.dataset.xboardPage, 'panel');
  assert.equal(state.scripts[0].src, '/theme/Xboard/assets/umi.js');
});

test('returning home before the deferred loader arrives does not boot Vue', () => {
  const state = boot({ headMode: 'panel', hash: '#guide' });
  assert.equal(state.document.documentElement.dataset.xboardPage, 'home');
  assert.deepEqual(state.scripts, []);
});

test('cross-mode navigation reloads once and intercepts Vue in capture phase', () => {
  const state = boot({ headMode: 'panel', hash: '#/login' });
  state.location.hash = '';
  assert.deepEqual(state.fire('popstate'), { stopped: true, capture: true });
  state.fire('hashchange');
  assert.equal(state.reloads, 1);
});

test('homepage restored from bfcache can enter the panel again', () => {
  const state = boot({ headMode: 'home', hash: '' });
  state.location.hash = '#/login';
  state.fire('popstate');
  assert.equal(state.reloads, 1);
  state.location.hash = '';
  state.fire('pageshow', { persisted: true });
  state.location.hash = '#/register';
  state.fire('popstate');
  assert.equal(state.reloads, 2);
});

test('section anchors and navigation inside the panel stay with their own router', () => {
  for (const [headMode, initialHash, nextHash] of [['home', '', '#guide'], ['panel', '#/login', '#/register']]) {
    const state = boot({ headMode, hash: initialHash });
    state.location.hash = nextHash;
    assert.equal(state.fire('popstate').stopped, false);
    assert.equal(state.reloads, 0);
  }
});

(function () {
  'use strict';
  var loader = document.getElementById('capy-panel-loading');
  var message = document.getElementById('capy-panel-loading-message');
  var app = document.getElementById('app');
  if (!loader || !app) return;
  var timer;
  var observer;
  function isPanel() { return location.hash.indexOf('#/') === 0; }
  function ready() {
    if (!app.querySelector('input, button, a[href]')) return false;
    loader.hidden = true;
    clearTimeout(timer);
    if (observer) observer.disconnect();
    return true;
  }
  function start() {
    if (!isPanel()) return;
    loader.hidden = false;
    if (ready()) return;
    clearTimeout(timer);
    timer = setTimeout(function () {
      message.textContent = '加载时间有点长，你可以继续等待，或重新加载。';
    }, 10000);
  }
  document.getElementById('capy-panel-retry').addEventListener('click', function (event) {
    event.preventDefault();
    location.reload();
  });
  window.addEventListener('xboard:panel-error', function () {
    clearTimeout(timer);
    message.textContent = '页面加载失败，请重新加载，或返回入口。';
  });
  window.addEventListener('hashchange', start);
  window.addEventListener('pageshow', start);
  observer = new MutationObserver(ready);
  observer.observe(app, { childList: true, subtree: true });
  start();
})();

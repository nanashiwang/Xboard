(function () {
  'use strict';
  var isPanel = function () { return location.hash.indexOf('#/') === 0; };
  var startedInPanel = isPanel();
  // The existing Vue router owns #/ paths; section anchors belong to the homepage.
  // Reload only when crossing that boundary, preserving query strings and history.
  var switchingPage = false;
  function crossPageBoundary(event) {
    if (isPanel() === startedInPanel) return;
    // Run before Vue's popstate listener so it cannot replace the homepage
    // history entry with its login redirect before the reload starts.
    event.stopImmediatePropagation();
    if (!switchingPage) {
      switchingPage = true;
      location.reload();
    }
  }
  window.addEventListener('popstate', crossPageBoundary, true);
  window.addEventListener('hashchange', crossPageBoundary, true);
  if (startedInPanel) {
    var entry = document.currentScript;
    var main = document.createElement('script');
    main.type = 'module';
    main.crossOrigin = 'anonymous';
    main.src = entry.dataset.panelSrc;
    main.onerror = function () {
      var app = document.getElementById('app');
      var message = document.createElement('p');
      message.textContent = '页面加载失败，请刷新重试，或返回首页。';
      var retry = document.createElement('button');
      retry.textContent = '重新加载';
      retry.onclick = function () { location.reload(); };
      var home = document.createElement('a');
      home.href = '/';
      home.textContent = '返回首页';
      app.replaceChildren(message, retry, document.createTextNode(' '), home);
    };
    document.head.appendChild(main);
    ['gift-card.js', 'client-download-entry.js'].forEach(function (name) {
      var script = document.createElement('script');
      script.src = window.settings.assets_path + '/' + name + '?v=' + encodeURIComponent(window.settings.version);
      document.body.appendChild(script);
    });
    return;
  }
  document.title = '卡皮巴拉 · 与你一起畅游全球网络';
  var root = document.querySelector('.capy-home');
  var menu = root.querySelector('.capy-menu');
  var navigation = root.querySelector('.capy-nav');
  root.setAttribute('data-enhanced', '');
  menu.hidden = false;
  function closeMenu() {
    menu.setAttribute('aria-expanded', 'false');
    menu.setAttribute('aria-label', '打开导航菜单');
    navigation.classList.remove('is-open');
  }
  menu.addEventListener('click', function () {
    var open = menu.getAttribute('aria-expanded') !== 'true';
    menu.setAttribute('aria-expanded', String(open));
    menu.setAttribute('aria-label', open ? '关闭导航菜单' : '打开导航菜单');
    navigation.classList.toggle('is-open', open);
  });
  navigation.addEventListener('click', function (event) {
    if (event.target.closest('a')) closeMenu();
  });
  document.addEventListener('click', function (event) {
    if (!event.target.closest('.capy-header')) closeMenu();
  });
  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape' && menu.getAttribute('aria-expanded') === 'true') {
      closeMenu();
      menu.focus();
    }
  });
})();

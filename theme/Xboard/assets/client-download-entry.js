(function () {
  'use strict';
  var style = document.createElement('style');
  style.textContent = '.xboard-download-entry{display:flex;align-items:center;gap:11px;min-height:42px;margin:4px 8px;padding:0 22px;border-radius:5px;color:inherit;text-decoration:none;font:inherit;box-sizing:border-box}.xboard-download-entry:hover{background:rgba(36,119,107,.12);color:var(--primary-color,#24776b)}.xboard-download-entry svg{width:19px;height:19px;flex:none}.xboard-download-start{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:14px;margin:0 0 18px;padding:18px 22px;border:1px solid rgba(36,119,107,.2);border-radius:8px;background:rgba(36,119,107,.06);color:inherit}.xboard-download-start p{margin:5px 0 0;font-size:13px;opacity:.7}.xboard-download-start a{white-space:nowrap;padding:8px 15px;border-radius:6px;background:var(--primary-color,#24776b);color:white;text-decoration:none}';
  document.head.appendChild(style);
  function signedIn() {
    try {
      var stored = JSON.parse(localStorage.getItem('VUE_NAIVE_ACCESS_TOKEN') || 'null');
      return stored && stored.value && (!stored.expire || stored.expire > Date.now());
    } catch (_) { return false; }
  }
  function sync() {
    var visible = signedIn() && !/\/(login|register|forgetpassword)(?:[/?#]|$)/.test(location.hash);
    if (!visible) {
      document.querySelectorAll('.xboard-download-entry,.xboard-download-start').forEach(function (node) { node.remove(); });
      return;
    }
    document.querySelectorAll('[role="menu"]').forEach(function (menu) {
      if (menu.querySelector('.xboard-download-entry')) return;
      var anchor = document.createElement('a');
      anchor.href = '/clients';
      anchor.className = 'xboard-download-entry';
      anchor.setAttribute('role', 'menuitem');
      anchor.innerHTML = '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"><path d="M12 3v12m-5-5 5 5 5-5M4 16v5h16v-5"/></svg><span>客户端下载</span>';
      var items = menu.querySelectorAll('[role="menuitem"]');
      var knowledge = Array.from(items).find(function (item) { return /使用文档|Knowledge|Documentation/.test(item.textContent); });
      if (knowledge) knowledge.after(anchor); else menu.appendChild(anchor);
    });
    var article = document.querySelector('article');
    var dashboard = /^#\/dashboard(?:[/?]|$)/.test(location.hash);
    var content = article && article.querySelector('.cus-scroll-y');
    if (content && dashboard && !content.querySelector('.xboard-download-start')) {
      var card = document.createElement('section');
      card.className = 'xboard-download-start';
      card.innerHTML = '<div><strong>在你的设备上开始使用</strong><p>下载适配的开源客户端，一键导入本站订阅。</p></div><a href="/clients">下载与导入 →</a>';
      content.prepend(card);
    }
    if (!dashboard) document.querySelectorAll('.xboard-download-start').forEach(function (node) { node.remove(); });
  }
  var pending = false;
  new MutationObserver(function () {
    if (pending) return;
    pending = true;
    requestAnimationFrame(function () { pending = false; sync(); });
  }).observe(document.body, { childList: true, subtree: true });
  window.addEventListener('hashchange', sync);
  window.addEventListener('storage', sync);
  sync();
})();

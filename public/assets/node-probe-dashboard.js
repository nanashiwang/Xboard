(() => {
  'use strict';
  const path = document.body.dataset.adminPath;
  if (!path) return;
  const pageHash = '#/?page=node-quality';
  const activeClasses = ['bg-secondary', 'text-secondary-foreground', 'shadow-sm', 'hover:bg-secondary/80'];
  const initialTitle = document.title;
  let page, frame, host, heading, title, pageRequest, pageTimer, auth = '', listScroll = 0, pendingScroll = null;
  const token = () => {
    try {
      const t = JSON.parse(localStorage.getItem('XBOARD_ACCESS_TOKEN'));
      return t && (!t.expire || t.expire > Date.now()) ? t.value : '';
    } catch { return ''; }
  };
  const route = () => {
    const [pathname, search = ''] = location.hash.slice(1).split('?');
    return (!pathname || pathname === '/') && new URLSearchParams(search).get('page') === 'node-quality';
  };
  const theme = () => document.documentElement.classList.contains('dark') ? 'dark' : 'light';
  function syncTheme() {
    frame?.contentWindow?.postMessage({type: 'node-probes:theme', theme: theme()}, location.origin);
  }
  function unmount() {
    pageRequest?.abort(); clearTimeout(pageTimer); pageRequest = null;
    page?.remove(); title?.remove();
    host?.classList.remove('np-page-host');
    heading?.parentElement?.classList.remove('np-page-heading');
    page = frame = host = heading = title = null;
    pendingScroll = null;
    document.body.classList.remove('np-page-active');
    if (document.title === '节点质量 · ' + initialTitle) document.title = initialTitle;
  }
  async function loadPage(target, status, retry) {
    pageRequest?.abort(); clearTimeout(pageTimer);
    const request = new AbortController(); pageRequest = request;
    status.textContent = '正在加载节点质量…'; status.hidden = false; retry.hidden = true;
    const fail = () => {
      if (request !== pageRequest || target !== frame) return;
      status.textContent = '节点质量暂时未能加载，请重试。'; retry.hidden = false;
    };
    pageTimer = setTimeout(() => { request.abort(); fail(); }, 15000);
    try {
      const url = new URL('/' + path + '/node-probes?' + new URLSearchParams({embedded: '1', theme: theme()}), location.origin);
      const response = await fetch(url, {credentials:'same-origin', cache:'no-store', redirect:'error', signal:request.signal});
      if (!response.ok || !(response.headers.get('content-type') || '').includes('text/html')) throw new Error('Page unavailable');
      const html = await response.text();
      if (request !== pageRequest || target !== frame || !target.isConnected) return;
      // Keep the existing same-origin isolation while making document loading observable and retryable.
      const document = new DOMParser().parseFromString(html, 'text/html');
      const base = document.createElement('base'); base.href = url.href; document.head.prepend(base);
      target.srcdoc = '<!doctype html>' + document.documentElement.outerHTML;
    } catch { fail(); }
  }
  function mount() {
    if (location.hash === '#node-quality') {
      location.replace(pageHash);
      return;
    }
    const current = token();
    if (auth !== current) { unmount(); auth = current; }
    const homeLink = document.querySelector('nav a[href="#/"]');
    let nav = document.getElementById('node-probe-nav');
    if (!current || !homeLink || location.hash.startsWith('#/sign-in')) {
      unmount(); nav?.remove(); return;
    }
    if (!nav) {
      nav = document.createElement('a'); nav.id = 'node-probe-nav'; nav.href = pageHash;
      nav.innerHTML = '<div class="mr-2"><svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 12h4l3-8 4 16 3-8h4"/></svg></div><span>节点质量</span>';
      nav.addEventListener('click', event => {
        if (event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) {
          document.querySelector('button[aria-controls="sidebar-menu"][aria-expanded="true"]')?.click();
        }
      });
      homeLink.after(nav);
    }
    const active = route();
    nav.className = homeLink.className.split(' ').filter(c => !activeClasses.includes(c)).join(' ') + (active ? ' ' + activeClasses.join(' ') : ' hover:bg-accent');
    if (active) { nav.setAttribute('aria-current', 'page'); homeLink.removeAttribute('aria-current'); }
    else { nav.removeAttribute('aria-current'); if (!location.hash || location.hash === '#/') homeLink.setAttribute('aria-current', 'page'); }
    if (!active) { unmount(); return; }
    if (page?.isConnected) return;
    unmount();
    // Keep the pinned React shell intact; only append owned elements to its stable page slots.
    const content = document.querySelector('main > div > div.flex-1');
    const originalHeading = document.querySelector('main h1');
    if (!content || !originalHeading) return;
    host = content; heading = originalHeading;
    title = document.createElement('h1'); title.id = 'node-quality-title'; title.className = heading.className; title.textContent = '节点质量';
    heading.parentElement.append(title); heading.parentElement.classList.add('np-page-heading');
    page = document.createElement('section'); page.id = 'node-quality-page'; page.setAttribute('aria-label', '节点质量');
    frame = document.createElement('iframe'); frame.id = 'node-quality-frame'; frame.title = '节点质量与探针管理';
    const status = document.createElement('p'); status.id = 'node-quality-loading'; status.setAttribute('role', 'status');
    const retry = document.createElement('button'); retry.type = 'button'; retry.id = 'node-quality-retry'; retry.textContent = '重新加载'; retry.hidden = true;
    const target = frame;
    retry.addEventListener('click', () => loadPage(target, status, retry));
    frame.addEventListener('load', syncTheme); page.append(status, retry, frame); host.append(page);
    host.classList.add('np-page-host'); document.body.classList.add('np-page-active'); host.scrollTop = 0;
    document.title = '节点质量 · ' + initialTitle;
    loadPage(target, status, retry);
  }
  window.addEventListener('message', event => {
    if (!frame || event.origin !== location.origin || event.source !== frame.contentWindow) return;
    if (event.data?.type === 'node-probes:ready') {
      clearTimeout(pageTimer);
      document.getElementById('node-quality-loading')?.setAttribute('hidden', '');
      document.getElementById('node-quality-retry')?.setAttribute('hidden', '');
      syncTheme();
    }
    if (event.data?.type === 'node-probes:height' && Number.isFinite(event.data.height)) {
      frame.style.height = Math.max(400, Math.min(200000, event.data.height)) + 'px';
      if (pendingScroll !== null) { host.scrollTop = pendingScroll; pendingScroll = null; }
    }
    if (event.data?.type === 'node-probes:history') {
      if (event.data.open) { listScroll = host.scrollTop; host.scrollTop = 0; }
      // The list height arrives after it is shown; restoring before that would clamp to zero.
      else pendingScroll = listScroll;
    }
  });
  const root = document.getElementById('root');
  if (root) new MutationObserver(mount).observe(root, {childList: true, subtree: true});
  new MutationObserver(syncTheme).observe(document.documentElement, {attributes: true, attributeFilter: ['class']});
  window.addEventListener('hashchange', mount);
  window.addEventListener('storage', event => { if (event.key === 'XBOARD_ACCESS_TOKEN' || event.key === null) mount(); });
  setInterval(mount, 30000);
  mount();
})();

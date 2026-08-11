(function () {
  'use strict';

  var STORAGE_KEY = 'VUE_NAIVE_ACCESS_TOKEN';
  var API_BASE = '/api/v1/user/gift-card';
  var redeemed = false;
  var lastCheckedCode = '';
  var rejectedCode = '';

  function getToken() {
    try {
      var stored = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || 'null');
      if (!stored || !stored.value || (stored.expire && stored.expire <= Date.now())) {
        return '';
      }
      return String(stored.value);
    } catch (error) {
      return '';
    }
  }

  function isAuthPage() {
    return /\/(login|register|forgetpassword)(?:[/?#]|$)/i.test(window.location.hash || window.location.pathname);
  }

  function createElement(tag, className, text) {
    var element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined) element.textContent = text;
    return element;
  }

  function isValidCode(code) {
    return code.length >= 8 && code.length <= 32;
  }

  function firstError(payload) {
    if (payload && payload.errors) {
      var keys = Object.keys(payload.errors);
      if (keys.length) {
        var error = payload.errors[keys[0]];
        return Array.isArray(error) ? error[0] : error;
      }
    }
    return payload && payload.message ? payload.message : '请求失败，请稍后重试';
  }

  async function request(action, code) {
    var token = getToken();
    if (!token) throw new Error('登录状态已失效，请重新登录');

    var response = await window.fetch(API_BASE + '/' + action, {
      method: 'POST',
      headers: {
        Authorization: token,
        'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
        'Content-Language': 'zh-CN'
      },
      body: new URLSearchParams({ code: code }).toString()
    });

    var payload;
    try {
      payload = await response.json();
    } catch (error) {
      throw new Error('服务器响应异常，请稍后重试');
    }

    if (!response.ok || payload.status === 'fail') {
      throw new Error(firstError(payload));
    }
    return payload.data || {};
  }

  function formatBytes(bytes) {
    var gb = Number(bytes) / 1073741824;
    return (Math.round(gb * 100) / 100) + ' GB 流量';
  }

  function rewardLines(rewards, type) {
    if (Number(type) === 3) return ['盲盒奖励（以实际兑换结果为准）'];

    var lines = [];
    if (Number(rewards.balance) > 0) lines.push('余额 ¥' + (Number(rewards.balance) / 100).toFixed(2));
    if (Number(rewards.transfer_enable) > 0) lines.push(formatBytes(rewards.transfer_enable));
    if (Number(rewards.expire_days) > 0) lines.push('有效期 +' + rewards.expire_days + ' 天');
    if (Number(rewards.device_limit) > 0) lines.push('设备数 +' + rewards.device_limit);
    if (rewards.reset_package) lines.push('重置当前套餐流量');
    if (rewards.plan_id) lines.push('兑换套餐权益');
    return lines.length ? lines : ['具体奖励以实际到账为准'];
  }

  function addStyle() {
    var style = document.createElement('style');
    style.textContent = [
      '#xboard-gift-card-entry{position:fixed;right:22px;bottom:22px;z-index:9998;border:0;border-radius:999px;padding:11px 18px;background:var(--primary-color,#18a058);color:#fff;font-size:14px;font-weight:600;box-shadow:0 8px 24px rgba(0,0,0,.2);cursor:pointer;transition:transform .18s,opacity .18s}',
      '#xboard-gift-card-entry:hover{transform:translateY(-2px)}',
      '#xboard-gift-card-entry[hidden],#xboard-gift-card-overlay[hidden]{display:none!important}',
      '#xboard-gift-card-overlay{position:fixed;inset:0;z-index:9999;display:flex;align-items:center;justify-content:center;padding:20px;background:rgba(0,0,0,.48);backdrop-filter:blur(2px)}',
      '.xgc-modal{width:min(430px,100%);border-radius:14px;background:#fff;color:#1f2329;box-shadow:0 18px 60px rgba(0,0,0,.28);overflow:hidden}',
      '.xgc-head{display:flex;align-items:flex-start;justify-content:space-between;padding:22px 24px 12px}',
      '.xgc-title{margin:0;font-size:20px;font-weight:700}.xgc-subtitle{margin:5px 0 0;color:#7a7f87;font-size:13px}',
      '.xgc-close{border:0;background:transparent;color:#777;font-size:25px;line-height:1;cursor:pointer}',
      '.xgc-body{padding:12px 24px 24px}.xgc-input{box-sizing:border-box;width:100%;height:42px;border:1px solid #d8dadd;border-radius:8px;padding:0 12px;background:#fff;color:#1f2329;font-size:15px;outline:none}',
      '.xgc-input:focus{border-color:var(--primary-color,#18a058);box-shadow:0 0 0 2px rgba(24,160,88,.12)}',
      '.xgc-message{min-height:20px;margin-top:10px;font-size:13px}.xgc-message.error{color:#d03050}.xgc-message.success{color:#18a058}',
      '.xgc-preview{display:none;margin-top:12px;border-radius:9px;padding:14px;background:#f5f7f9;font-size:14px;line-height:1.65}.xgc-preview.show{display:block}',
      '.xgc-preview-title{font-weight:700;font-size:15px}.xgc-preview-desc{color:#6f747c}.xgc-preview-rewards{margin:8px 0 0;padding-left:20px}',
      '.xgc-actions{display:flex;justify-content:flex-end;gap:10px;margin-top:18px}.xgc-btn{height:38px;border-radius:8px;padding:0 17px;border:1px solid #d8dadd;background:#fff;color:#333;cursor:pointer}',
      '.xgc-btn.primary{border-color:var(--primary-color,#18a058);background:var(--primary-color,#18a058);color:#fff}.xgc-btn:disabled{cursor:not-allowed;opacity:.5}',
      '@media(max-width:640px){#xboard-gift-card-entry{right:14px;bottom:76px}.xgc-modal{border-radius:12px}.xgc-head{padding:20px 20px 10px}.xgc-body{padding:10px 20px 22px}}',
      '@media(prefers-color-scheme:dark){.xgc-modal{background:#25262b;color:#f1f1f1}.xgc-input,.xgc-btn{background:#18191d;color:#f1f1f1;border-color:#4a4b50}.xgc-preview{background:#18191d}.xgc-subtitle,.xgc-preview-desc{color:#a9abb1}}'
    ].join('');
    document.head.appendChild(style);
  }

  function init() {
    addStyle();

    var entry = createElement('button', '', '兑换码');
    entry.id = 'xboard-gift-card-entry';
    entry.type = 'button';
    entry.hidden = true;
    entry.setAttribute('aria-label', '使用兑换码');

    var overlay = createElement('div');
    overlay.id = 'xboard-gift-card-overlay';
    overlay.hidden = true;
    overlay.innerHTML = [
      '<section class="xgc-modal" role="dialog" aria-modal="true" aria-labelledby="xgc-title">',
      '  <div class="xgc-head">',
      '    <div><h2 id="xgc-title" class="xgc-title">使用兑换码</h2><p class="xgc-subtitle">输入管理员发放的礼品卡兑换码</p></div>',
      '    <button type="button" class="xgc-close" aria-label="关闭">×</button>',
      '  </div>',
      '  <div class="xgc-body">',
      '    <input class="xgc-input" type="text" minlength="8" maxlength="32" autocomplete="off" placeholder="请输入兑换码">',
      '    <div class="xgc-message" aria-live="polite"></div>',
      '    <div class="xgc-preview"></div>',
      '    <div class="xgc-actions">',
      '      <button type="button" class="xgc-btn xgc-check">查询</button>',
      '      <button type="button" class="xgc-btn primary xgc-redeem" disabled>立即兑换</button>',
      '    </div>',
      '  </div>',
      '</section>'
    ].join('');

    document.body.appendChild(entry);
    document.body.appendChild(overlay);

    var input = overlay.querySelector('.xgc-input');
    var message = overlay.querySelector('.xgc-message');
    var preview = overlay.querySelector('.xgc-preview');
    var checkButton = overlay.querySelector('.xgc-check');
    var redeemButton = overlay.querySelector('.xgc-redeem');
    var closeButton = overlay.querySelector('.xgc-close');

    function setMessage(text, type) {
      message.textContent = text || '';
      message.className = 'xgc-message' + (type ? ' ' + type : '');
    }

    function syncRedeemButton() {
      var code = input.value.trim();
      redeemButton.disabled = !redeemed && (!isValidCode(code) || rejectedCode === code);
    }

    function setBusy(busy) {
      input.disabled = busy || redeemed;
      checkButton.disabled = busy || redeemed;
      if (busy) {
        redeemButton.disabled = true;
      } else {
        syncRedeemButton();
      }
    }

    function reset() {
      redeemed = false;
      lastCheckedCode = '';
      rejectedCode = '';
      input.disabled = false;
      input.value = '';
      checkButton.disabled = false;
      checkButton.textContent = '查询';
      redeemButton.disabled = true;
      redeemButton.textContent = '立即兑换';
      preview.className = 'xgc-preview';
      preview.textContent = '';
      setMessage('');
    }

    function close() {
      overlay.hidden = true;
      document.body.style.overflow = '';
      if (redeemed) window.location.reload();
    }

    function open() {
      reset();
      overlay.hidden = false;
      document.body.style.overflow = 'hidden';
      window.setTimeout(function () { input.focus(); }, 0);
    }

    function renderPreview(data) {
      var info = data.code_info || {};
      var template = info.template || {};
      preview.textContent = '';
      preview.appendChild(createElement('div', 'xgc-preview-title', template.name || '兑换码'));
      if (template.description) preview.appendChild(createElement('div', 'xgc-preview-desc', template.description));

      var rewards = createElement('ul', 'xgc-preview-rewards');
      rewardLines(data.reward_preview || {}, template.type).forEach(function (line) {
        rewards.appendChild(createElement('li', '', line));
      });
      preview.appendChild(rewards);
      preview.className = 'xgc-preview show';

      if (data.can_redeem) {
        lastCheckedCode = input.value.trim();
        rejectedCode = '';
        setMessage('兑换码可用，可以立即兑换。', 'success');
      } else {
        lastCheckedCode = '';
        rejectedCode = input.value.trim();
        setMessage(data.reason || '当前账号不满足兑换条件', 'error');
      }
      syncRedeemButton();
    }

    async function checkCode() {
      var code = input.value.trim();
      lastCheckedCode = '';
      rejectedCode = '';
      redeemButton.disabled = true;
      preview.className = 'xgc-preview';
      preview.textContent = '';

      if (!isValidCode(code)) {
        setMessage('兑换码长度应为 8～32 位', 'error');
        syncRedeemButton();
        return false;
      }

      setMessage('正在查询…');
      setBusy(true);
      try {
        renderPreview(await request('check', code));
        return lastCheckedCode === code;
      } catch (error) {
        setMessage(error.message, 'error');
        return false;
      } finally {
        setBusy(false);
      }
    }

    async function redeemCode() {
      if (redeemed) {
        window.location.reload();
        return;
      }

      var code = input.value.trim();
      if (!isValidCode(code)) {
        setMessage('兑换码长度应为 8～32 位', 'error');
        syncRedeemButton();
        return;
      }

      if (lastCheckedCode !== code && !(await checkCode())) {
        return;
      }

      setMessage('正在兑换…');
      setBusy(true);
      try {
        var data = await request('redeem', code);
        redeemed = true;
        preview.textContent = '';
        preview.appendChild(createElement('div', 'xgc-preview-title', data.message || '兑换成功！'));
        preview.appendChild(createElement('div', 'xgc-preview-desc', data.template_name || '权益已发放到当前账号'));
        preview.className = 'xgc-preview show';
        setMessage('兑换成功，刷新页面后即可看到最新权益。', 'success');
        redeemButton.textContent = '刷新页面';
        redeemButton.disabled = false;
        checkButton.disabled = true;
        input.disabled = true;
      } catch (error) {
        setMessage(error.message, 'error');
        setBusy(false);
      }
    }

    function syncVisibility() {
      entry.hidden = !getToken() || isAuthPage();
      if (entry.hidden && !overlay.hidden) close();
    }

    entry.addEventListener('click', open);
    closeButton.addEventListener('click', close);
    checkButton.addEventListener('click', checkCode);
    redeemButton.addEventListener('click', redeemCode);
    input.addEventListener('input', function () {
      var code = input.value.trim();
      if (code !== lastCheckedCode) {
        lastCheckedCode = '';
        rejectedCode = '';
        preview.className = 'xgc-preview';
        preview.textContent = '';
        setMessage('');
      }
      syncRedeemButton();
    });
    input.addEventListener('keydown', function (event) {
      if (event.key === 'Enter') checkCode();
    });
    overlay.addEventListener('click', function (event) {
      if (event.target === overlay) close();
    });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && !overlay.hidden) close();
    });
    window.addEventListener('hashchange', syncVisibility);
    window.addEventListener('storage', syncVisibility);
    window.setInterval(syncVisibility, 1000);
    syncVisibility();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

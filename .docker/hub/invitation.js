(function () {
  'use strict';
  // Only public invitation codes travel between the Hub and the application.
  // Never accept a destination URL, subscription token or account credential.
  var code = new URLSearchParams(location.search).get('invite');
  if (!code || !/^[A-Za-z0-9]{8}$/.test(code)) return;
  var query = '?invite=' + encodeURIComponent(code);
  document.querySelectorAll('[data-app-entry]').forEach(function (link) {
    var target = new URL(link.href);
    if (target.origin !== 'https://capybarago.uk' && target.origin !== 'https://taige.us' && target.origin !== 'https://app.capybarahub.fyi') return;
    link.href = target.origin + '/#/register?code=' + encodeURIComponent(code);
  });
  document.querySelectorAll('[data-hub-link]').forEach(function (link) {
    var target = new URL(link.href);
    if (target.origin === location.origin) link.href = target.pathname + query;
  });
})();

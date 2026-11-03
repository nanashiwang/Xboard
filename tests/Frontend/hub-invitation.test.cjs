const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../../.docker/hub/invitation.js'), 'utf8');
function boot(search) {
  const apps = [{ href: 'https://capybarago.uk/' }, { href: 'https://taige.us/' }, { href: 'https://example.com/' }];
  const hub = [{ href: 'https://capybarahub.fyi/downloads.html' }, { href: 'https://capybarahub.fyi/' }, { href: 'https://github.com/package' }];
  vm.runInNewContext(source, {
    URL, URLSearchParams, location: { search, origin: 'https://capybarahub.fyi' },
    document: { querySelectorAll: selector => selector === '[data-app-entry]' ? apps : hub },
  });
  return { apps, hub };
}
test('invitation stays on the Hub and both approved entry links preserve registration attribution', () => {
  const { apps, hub } = boot('?invite=Ab123456&redirect=https://example.com');
  assert.equal(apps[0].href, 'https://capybarago.uk/#/register?code=Ab123456');
  assert.equal(apps[1].href, 'https://taige.us/#/register?code=Ab123456');
  assert.equal(apps[2].href, 'https://example.com/');
  assert.equal(hub[0].href, '/downloads.html?invite=Ab123456');
  assert.equal(hub[1].href, '/?invite=Ab123456');
  assert.equal(hub[2].href, 'https://github.com/package');
});
test('absent, malformed and subscription-like tokens leave navigation unchanged', () => {
  for (const query of ['', '?invite=', '?invite=%3Cscript%3E', '?invite=' + 'a'.repeat(32), '?invite=abc%26test', '?token=Ab123456']) {
    const { apps, hub } = boot(query);
    assert.equal(apps[0].href, 'https://capybarago.uk/');
    assert.equal(hub[0].href, 'https://capybarahub.fyi/downloads.html');
  }
});
test('the shipped website theme copies the same navigation invitation contract', () => {
  const theme = fs.readFileSync(path.join(__dirname, '../../theme/Xboard/assets/umi.js'), 'utf8');
  assert.equal(theme.split('https://capybarahub.fyi/?invite=${encodeURIComponent(e.code)}').length - 1, 1);
  assert.ok(!theme.includes('${window.location.protocol}//${window.location.host}/#/register?code=${e.code}'));
});

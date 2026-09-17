#!/usr/bin/env bash
# Production-only: add taige.us while retaining board.taige.us unchanged.
set -euo pipefail
cd /root/Xboard
phase="${1:?Expected prepare, activate, or promote}"
primary_conf=/etc/nginx/sites-enabled/taige.us.conf
webroot=/var/www/xboard-acme
test -f /etc/nginx/sites-enabled/board.taige.us.conf
docker compose config --services | grep -Fxq xboard

case "$phase" in
  prepare)
    backup="/root/Xboard/backups/primary-domain-$(date -u +%Y%m%d-%H%M%S)"
    install -d -m 700 "$backup"
    cp -p /etc/nginx/sites-enabled/board.taige.us.conf "$backup/board.taige.us.conf"
    cp -p .env "$backup/env.before"
    if [ -f "$primary_conf" ]; then
      grep -Fq '# Xboard managed primary domain' "$primary_conf"
      cp -p "$primary_conf" "$backup/taige.us.conf"
    fi
    python3 - "$backup" <<'PY'
import os, sqlite3, sys
target = sys.argv[1] + '/database.sqlite'
with sqlite3.connect('.docker/.data/database.sqlite') as source:
    with sqlite3.connect(target) as dest:
        source.backup(dest)
os.chmod(target, 0o600)
PY
    install -d -m 755 "$webroot/.well-known/acme-challenge"
    printf 'xboard-taige-domain-ready' > "$webroot/.well-known/acme-challenge/xboard-domain-probe"
    if [ ! -f "$primary_conf" ]; then
      cat > "$primary_conf" <<'NGINX'
# Xboard managed primary domain
server {
    listen 80;
    listen [::]:80;
    server_name taige.us;
    location ^~ /.well-known/acme-challenge/ {
        root /var/www/xboard-acme;
        default_type text/plain;
    }
    location / { return 301 https://taige.us$request_uri; }
}
NGINX
    fi
    nginx -t
    systemctl reload nginx
    echo "Prepared primary domain; backup=$backup"
    ;;
  activate)
    grep -Fq '# Xboard managed primary domain' "$primary_conf"
    if ! command -v certbot >/dev/null; then
      apt-get update -qq </dev/null
      DEBIAN_FRONTEND=noninteractive apt-get install -y -qq certbot </dev/null
    fi
    certbot certonly --webroot -w "$webroot" -d taige.us --cert-name taige.us \
      --non-interactive --agree-tos --register-unsafely-without-email --keep-until-expiring </dev/null
    cp -p "$primary_conf" /etc/nginx/taige.us.before-activation
    python3 - <<'PY'
from pathlib import Path
source = Path('/etc/nginx/sites-enabled/board.taige.us.conf').read_text()
https = source[source.index('server {', source.index('server {') + 1):]
https = https.replace('server_name board.taige.us;', 'server_name taige.us;')
https = https.replace('/etc/nginx/ssl/board.taige.us/', '/etc/letsencrypt/live/taige.us/')
target = Path('/etc/nginx/sites-enabled/taige.us.conf')
http = target.read_text().split('\nserver {\n    listen 443', 1)[0]
target.write_text(http.rstrip() + '\n\n' + https)
PY
    if ! nginx -t; then
      cp -p /etc/nginx/taige.us.before-activation "$primary_conf"
      exit 1
    fi
    systemctl reload nginx
    install -d -m 755 /etc/letsencrypt/renewal-hooks/deploy
    cat > /etc/letsencrypt/renewal-hooks/deploy/xboard-nginx <<'HOOK'
#!/bin/sh
set -eu
nginx -t
systemctl reload nginx
HOOK
    chmod 755 /etc/letsencrypt/renewal-hooks/deploy/xboard-nginx
    systemctl enable --now certbot.timer
    curl --noproxy '*' --resolve taige.us:443:127.0.0.1 -fsS https://taige.us/ -o /dev/null
    openssl x509 -in /etc/letsencrypt/live/taige.us/fullchain.pem -noout -issuer -dates -ext subjectAltName
    ;;
  promote)
    test -s /etc/letsencrypt/live/taige.us/fullchain.pem
    curl --noproxy '*' --resolve taige.us:443:127.0.0.1 -fsS https://taige.us/ -o /dev/null
    docker exec -i xboard-xboard-1 php <<'PHP'
<?php
require '/www/vendor/autoload.php';
$app = require '/www/bootstrap/app.php';
$app->make(Illuminate\Contracts\Console\Kernel::class)->bootstrap();
Illuminate\Support\Facades\DB::transaction(function () {
    admin_setting(['app_url' => 'https://taige.us', 'subscribe_url' => 'https://taige.us']);
    $articles = Illuminate\Support\Facades\DB::table('v2_knowledge')
        ->where('body', 'like', '%https://board.taige.us/downloads/%')->get(['id', 'body']);
    foreach ($articles as $article) {
        Illuminate\Support\Facades\DB::table('v2_knowledge')->where('id', $article->id)->update([
            'body' => str_replace('https://board.taige.us/downloads/', 'https://taige.us/downloads/', $article->body),
            'updated_at' => time(),
        ]);
    }
    Illuminate\Support\Facades\DB::table('v2_payment')->where('id', 2)
        ->where('payment', 'StripeCheckout')->update(['notify_domain' => 'https://taige.us']);
});
echo 'Primary app URL: '.admin_setting('app_url').PHP_EOL;
echo 'Subscription URL: '.admin_setting('subscribe_url').PHP_EOL;
PHP
    python3 - <<'PY'
from pathlib import Path
import re
p = Path('.env')
s = p.read_text()
updated, count = re.subn(r'^APP_URL=.*$', 'APP_URL=https://taige.us', s, flags=re.M)
if count == 0:
    updated = s.rstrip() + '\nAPP_URL=https://taige.us\n'
p.write_text(updated)
PY
    docker exec xboard-xboard-1 php artisan config:clear
    docker exec xboard-xboard-1 php artisan octane:reload
    echo 'Primary domain promoted; board.taige.us and existing payment callback remain available.'
    ;;
  *) echo 'Unknown phase' >&2; exit 2 ;;
esac

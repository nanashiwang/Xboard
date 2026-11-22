#!/usr/bin/env bash
set -euo pipefail
# GitHub-hosted macOS runner only. Keep signing material outside the checkout.
umask 077
signing_dir=$(mktemp -d "$RUNNER_TEMP/capybara-signing.XXXXXX")
cert_keychain="$signing_dir/signing.keychain-db"
keychain_password=$(openssl rand -hex 32)
printf '%s' "$APPLE_CERTIFICATE" | base64 -D > "$signing_dir/identity.p12"
security create-keychain -p "$keychain_password" "$cert_keychain"
security unlock-keychain -p "$keychain_password" "$cert_keychain"
security set-keychain-settings -lut 7200 "$cert_keychain"
security import "$signing_dir/identity.p12" -k "$cert_keychain" -P "$APPLE_CERTIFICATE_PASSWORD" -T /usr/bin/codesign >/dev/null
rm "$signing_dir/identity.p12"
security set-key-partition-list -S apple-tool:,apple:,codesign: -s -k "$keychain_password" "$cert_keychain" >/dev/null
# Preserve the runner's login keychain and normal certificate search path.
keychains=()
while IFS= read -r path; do keychains+=("$path"); done < <(security list-keychains -d user | sed -E 's/^[[:space:]]*"//;s/"$//')
security list-keychains -d user -s "$cert_keychain" "${keychains[@]}"
identity=$(security find-identity -v -p codesigning "$cert_keychain" | sed -nE 's/.*"(Developer ID Application: [^"]+)"/\1/p')
[[ -n "$identity" && "$identity" != *$'\n'* ]]
# Two different executables must be able to rotate the same Keychain item silently.
security create-keychain -p "$keychain_password" "$signing_dir/probe.keychain-db"
security unlock-keychain -p "$keychain_password" "$signing_dir/probe.keychain-db"
for generation in 1 2; do
  clang -Wno-deprecated-declarations -framework Security -framework CoreFoundation -DGENERATION="$generation" scripts/keychain-upgrade-probe.c -o "$signing_dir/probe-$generation"
  codesign --force --timestamp --options runtime --sign "$identity" --identifier us.taige.capybara.session-probe "$signing_dir/probe-$generation"
  "$signing_dir/probe-$generation" "$signing_dir/probe.keychain-db"
done
security delete-keychain "$signing_dir/probe.keychain-db"
jq -n --arg id "$identity" '{bundle:{macOS:{signingIdentity:$id}}}' > "$signing_dir/signed.json"
printf 'CAPYBARA_SIGNING_CONFIG=%s\nCAPYBARA_DEVELOPER_ID_BUILD=1\n' "$signing_dir/signed.json" >> "$GITHUB_ENV"

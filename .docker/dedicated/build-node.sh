#!/usr/bin/env bash
set -euo pipefail

# Rebuild only the verified production node revision, with the idle-user fix.
# Requires Go 1.26.2, curl, tar and patch. Does not deploy or restart services.
revision=0a29338e1f102a462363ce3527417029f89bab28
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
output=${1:?Usage: build-node.sh /absolute/output/xboard-node-linux-amd64}
case "$output" in /*) ;; *) echo 'Output path must be absolute' >&2; exit 1 ;; esac
test "$(go env GOVERSION)" = go1.26.2 || { echo 'Go 1.26.2 is required' >&2; exit 1; }
build_dir=$(mktemp -d)
trap 'rm -rf -- "$build_dir"' EXIT
curl --fail --location --retry 3 "https://codeload.github.com/cedar2025/xboard-node/tar.gz/$revision" -o "$build_dir/source.tar.gz"
mkdir "$build_dir/source"
tar -xzf "$build_dir/source.tar.gz" -C "$build_dir/source" --strip-components=1
cd "$build_dir/source"
patch -p1 < "$script_dir/node-idle-start.patch"
go test -race ./internal/service
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build \
  -tags 'with_quic,with_utls,with_wireguard,with_acme,with_clash_api' \
  -trimpath -ldflags '-s -w -X main.version=0a29338-dedicated.1 -X main.commit=0a29338 -X main.buildTime=2026-10-12' \
  -o "$output" ./cmd/xboard-node

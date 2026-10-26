# QUIC identity observer (private operational helper)

This standalone helper performs only a QUIC/TLS handshake and immediately closes
it. It never opens bidirectional or unidirectional streams, sends application
QUIC datagrams, or sends Hysteria2 authentication. `InsecureSkipVerify` is confined
to certificate collection. A successful result is an untrusted observation, not
an approved key or proof of provider identity.

Input is one bounded JSON object on stdin, at most 4096 bytes, with exactly the
supported fields `ip` (public IP literal), `port` (integer 1–65535), `sni` (DNS
name), and optional `alpn` (array of strings; default `["h3"]`). Unknown/duplicate
fields, private/special-purpose IPs, hostname destinations and trailing JSON are
rejected. Production entry rejects loopback; internal `observe` permits loopback
so tests can exercise actual QUIC without weakening the CLI policy. IPv4 and IPv6
loopback handshakes are covered.

Stdout is **private** JSON: either `pin` (Base64 SHA256 of leaf SPKI DER),
`not_before`/`not_after` (Unix seconds), and `certificate_time_valid`, or only a
fixed `reason`. Capture it to restricted memory/files; never publish it in CI
logs. Raw errors, endpoints and SNI are not printed. Exit 0 = certificate observed,
1 = failed/timeout, 2 = invalid input. The shared 8-second deadline includes stdin
reading and the complete handshake. Expired certificates can be observed but are
explicitly flagged invalid, never approved.

Pinned dependency: official cached `github.com/quic-go/quic-go v0.59.0`; runtime
indirect dependencies are pinned by go.mod/go.sum. No credentials or production
configuration are read or written.

Verified with Go 1.26.2:

```
GOPROXY=off GOSUMDB=off go mod verify
GOPROXY=off GOSUMDB=off go test -mod=readonly -race -v ./...
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 GOPROXY=off GOSUMDB=off go build -mod=readonly -trimpath -buildvcs=false -ldflags='-s -w' -o bin/quic-observer-linux-amd64 .
CGO_ENABLED=0 GOOS=darwin GOARCH=arm64 GOPROXY=off GOSUMDB=off go build -mod=readonly -trimpath -buildvcs=false -ldflags='-s -w' -o bin/quic-observer-darwin-arm64 .
```

All 8 local tests passed with race detection. They cover actual IPv4/IPv6 QUIC,
exact leaf SPKI/time extraction, SNI/ALPN, no application streams/datagrams,
expired-certificate flagging, shared input/handshake deadlines, restricted input
and fixed error redaction. Both binaries built; `verification.json` contains their
sizes and SHA256. No production or external endpoint has been contacted by this
helper during development. The offline `go mod tidy` attempt requested an uncached
upstream-test-only gomock module and stopped; this helper's own readonly build,
tests and dependency verification require no network downloads and all passed.

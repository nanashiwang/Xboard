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

Pinned dependency: `github.com/quic-go/quic-go v0.59.0`; runtime
indirect dependencies are pinned by go.mod/go.sum. No credentials or production
configuration are read or written.

Build and test with Go 1.26.2. Download the exact pinned modules once, verify their
checksums, and build with readonly module metadata. `GOPROXY=off` can be used after
the required modules are already cached:

```
go mod download
go mod verify
go test -mod=readonly -race -v ./...
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -mod=readonly -trimpath -buildvcs=false -ldflags='-s -w' -o bin/quic-observer-linux-amd64 .
CGO_ENABLED=0 GOOS=darwin GOARCH=arm64 go build -mod=readonly -trimpath -buildvcs=false -ldflags='-s -w' -o bin/quic-observer-darwin-arm64 .
```

The tests use loopback IPv4/IPv6 QUIC to check leaf SPKI/time extraction, SNI/ALPN,
absence of application streams/datagrams, expired-certificate flagging, shared
input/handshake deadlines, restricted input, and fixed error redaction. The
no-application-data fixture accepts the connection with `ListenAddrEarly`: the
observer intentionally closes immediately after collecting the certificate, so
the fixture must not require the server's normal handshake-complete accept.
This changes only the test listener; the observer still sends no application
data and keeps the same 8-second limit.

The preparation workflow computes the SHA256 of its own Linux build before
transfer. It installs the fixed sibling filename with mode 0700 in the private
temporary directory. `prepare.py` checks that hash and the private file ownership
and permissions before execution, and binds the hash into the private plan.
Binary hashes are build outputs; no pre-generated local verification file is
required. Keep compiled binaries out of the repository and do not print the
helper's private stdout when using it against actual endpoints.

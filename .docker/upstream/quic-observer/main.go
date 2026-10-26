// quic-observer performs certificate discovery only. Its stdout is PRIVATE.
// It never opens a stream, sends a QUIC datagram, sends Hysteria2 credentials,
// or writes any trusted configuration. InsecureSkipVerify is confined to this
// observer; the result is an observation, not an authenticated provider identity.
package main

import (
	"bytes"
	"context"
	"crypto/sha256"
	"crypto/tls"
	"encoding/base64"
	"encoding/json"
	"errors"
	"io"
	"log"
	"net"
	"net/netip"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/quic-go/quic-go"
)

const totalBudget = 8 * time.Second
const maxInput = 4096

type request struct {
	IP   string   `json:"ip"`
	Port int      `json:"port"`
	SNI  string   `json:"sni"`
	ALPN []string `json:"alpn"`
}

type result struct {
	Reason               string `json:"reason,omitempty"`
	Pin                  string `json:"pin,omitempty"`
	NotBefore            *int64 `json:"not_before,omitempty"`
	NotAfter             *int64 `json:"not_after,omitempty"`
	CertificateTimeValid *bool  `json:"certificate_time_valid,omitempty"`
}

// IsGlobalUnicast also accepts several special-purpose ranges. The CLI rejects
// these explicitly, as well as private, mapped-private, multicast and link-local
// addresses. observe() deliberately bypasses this CLI policy for loopback tests.
var nonPublic = []netip.Prefix{
	netip.MustParsePrefix("0.0.0.0/8"), netip.MustParsePrefix("10.0.0.0/8"),
	netip.MustParsePrefix("100.64.0.0/10"), netip.MustParsePrefix("127.0.0.0/8"),
	netip.MustParsePrefix("169.254.0.0/16"), netip.MustParsePrefix("172.16.0.0/12"),
	netip.MustParsePrefix("192.0.0.0/24"), netip.MustParsePrefix("192.0.2.0/24"),
	netip.MustParsePrefix("192.88.99.0/24"),
	netip.MustParsePrefix("192.168.0.0/16"), netip.MustParsePrefix("198.18.0.0/15"),
	netip.MustParsePrefix("198.51.100.0/24"), netip.MustParsePrefix("203.0.113.0/24"),
	netip.MustParsePrefix("224.0.0.0/4"), netip.MustParsePrefix("240.0.0.0/4"),
	netip.MustParsePrefix("::/96"), netip.MustParsePrefix("64:ff9b::/96"), netip.MustParsePrefix("64:ff9b:1::/48"),
	netip.MustParsePrefix("100::/64"), netip.MustParsePrefix("2001::/23"),
	netip.MustParsePrefix("2001:db8::/32"), netip.MustParsePrefix("2002::/16"), netip.MustParsePrefix("3fff::/20"),
	netip.MustParsePrefix("fc00::/7"), netip.MustParsePrefix("fe80::/10"),
	netip.MustParsePrefix("ff00::/8"),
}

func publicAddress(text string) (netip.Addr, bool) {
	ip, err := netip.ParseAddr(text)
	if err != nil || ip.Zone() != "" {
		return netip.Addr{}, false
	}
	ip = ip.Unmap()
	if !ip.IsGlobalUnicast() || ip.IsPrivate() || ip.IsLoopback() || ip.IsLinkLocalUnicast() {
		return netip.Addr{}, false
	}
	for _, prefix := range nonPublic {
		if prefix.Contains(ip) {
			return netip.Addr{}, false
		}
	}
	return ip, true
}

func validSNI(s string) bool {
	if len(s) == 0 || len(s) > 253 {
		return false
	}
	for _, ch := range s {
		if !((ch >= 'a' && ch <= 'z') || (ch >= 'A' && ch <= 'Z') ||
			(ch >= '0' && ch <= '9') || ch == '-' || ch == '_' || ch == '.') {
			return false
		}
	}
	for _, label := range strings.Split(strings.TrimSuffix(s, "."), ".") {
		if len(label) == 0 || len(label) > 63 {
			return false
		}
	}
	return true
}

func parseRequest(data []byte) (request, bool) {
	var req request
	if len(data) == 0 || len(data) > maxInput {
		return req, false
	}
	// Reject duplicate names before the typed decoder can silently overwrite one.
	keys := json.NewDecoder(bytes.NewReader(data))
	first, err := keys.Token()
	if err != nil || first != json.Delim('{') {
		return request{}, false
	}
	seen := map[string]bool{}
	for keys.More() {
		key, err := keys.Token()
		name, isName := key.(string)
		if err != nil || !isName || seen[name] {
			return request{}, false
		}
		seen[name] = true
		var value json.RawMessage
		if keys.Decode(&value) != nil {
			return request{}, false
		}
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&req); err != nil {
		return request{}, false
	}
	var extra any
	if err := decoder.Decode(&extra); err != io.EOF {
		return request{}, false
	}
	ip, ok := publicAddress(req.IP)
	if !ok || req.Port < 1 || req.Port > 65535 || !validSNI(req.SNI) || len(req.ALPN) > 8 {
		return request{}, false
	}
	req.IP = ip.String()
	if len(req.ALPN) == 0 {
		req.ALPN = []string{"h3"}
	}
	for _, protocol := range req.ALPN {
		if len(protocol) == 0 || len(protocol) > 255 {
			return request{}, false
		}
		for _, ch := range protocol {
			if ch < 33 || ch > 126 {
				return request{}, false
			}
		}
	}
	return req, true
}

func classifyError(ctx context.Context, err error) string {
	if ctx.Err() != nil || errors.Is(err, context.DeadlineExceeded) || errors.Is(err, context.Canceled) {
		return "identity_timeout"
	}
	var timed net.Error
	if errors.As(err, &timed) && timed.Timeout() {
		return "identity_timeout"
	}
	var transport *quic.TransportError
	if errors.As(err, &transport) && transport.ErrorCode >= 0x100 && transport.ErrorCode <= 0x1ff {
		return "tls_failed"
	}
	var network *net.OpError
	if errors.As(err, &network) {
		return "quic_unreachable"
	}
	return "quic_handshake_failed"
}

// observe accepts loopback endpoints for tests. The executable always calls
// parseRequest first, enforcing literal globally reachable destination addresses.
func observe(ctx context.Context, req request) result {
	ctx, cancel := context.WithTimeout(ctx, totalBudget)
	defer cancel()
	deadline, _ := ctx.Deadline()
	remaining := time.Until(deadline)
	if remaining <= 0 {
		return result{Reason: "identity_timeout"}
	}
	protocols := req.ALPN
	if len(protocols) == 0 {
		protocols = []string{"h3"}
	}
	conn, err := quic.DialAddr(ctx, net.JoinHostPort(req.IP, strconv.Itoa(req.Port)), &tls.Config{
		ServerName: req.SNI, NextProtos: protocols, MinVersion: tls.VersionTLS13,
		InsecureSkipVerify: true, // Certificate discovery only; never used by a proxy.
	}, &quic.Config{
		HandshakeIdleTimeout: remaining, MaxIdleTimeout: remaining,
		MaxIncomingStreams: -1, MaxIncomingUniStreams: -1,
		EnableDatagrams: false, KeepAlivePeriod: 0,
	})
	if err != nil {
		return result{Reason: classifyError(ctx, err)}
	}
	defer conn.CloseWithError(0, "identity observation complete")
	certificates := conn.ConnectionState().TLS.PeerCertificates
	if len(certificates) == 0 || len(certificates[0].RawSubjectPublicKeyInfo) == 0 {
		return result{Reason: "certificate_invalid"}
	}
	leaf := certificates[0]
	spki := sha256.Sum256(leaf.RawSubjectPublicKeyInfo)
	start, end := leaf.NotBefore.Unix(), leaf.NotAfter.Unix()
	now := time.Now()
	valid := !now.Before(leaf.NotBefore) && !now.After(leaf.NotAfter)
	return result{Pin: base64.StdEncoding.EncodeToString(spki[:]), NotBefore: &start, NotAfter: &end, CertificateTimeValid: &valid}
}

func run(ctx context.Context, input io.Reader, output io.Writer) int {
	type inputResult struct {
		body []byte
		err  error
	}
	read := make(chan inputResult, 1)
	go func() {
		body, err := io.ReadAll(io.LimitReader(input, maxInput+1))
		read <- inputResult{body, err}
	}()
	var answer result
	code := 1
	select {
	case <-ctx.Done():
		answer = result{Reason: "identity_timeout"}
	case received := <-read:
		req, ok := parseRequest(received.body)
		if received.err != nil || !ok {
			answer, code = result{Reason: "invalid_input"}, 2
		} else {
			answer = observe(ctx, req)
			if answer.Reason == "" {
				code = 0
			}
		}
	}
	if json.NewEncoder(output).Encode(answer) != nil {
		return 1
	}
	return code
}

func main() {
	// Suppress quic-go diagnostics, which can contain a destination. This process
	// has no other log consumer; callers should capture stdout as private data.
	log.SetOutput(io.Discard)
	ctx, cancel := context.WithTimeout(context.Background(), totalBudget)
	code := run(ctx, os.Stdin, os.Stdout)
	cancel()
	os.Exit(code)
}

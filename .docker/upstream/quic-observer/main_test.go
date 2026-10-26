package main

import (
	"bytes"
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/sha256"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/base64"
	"encoding/json"
	"errors"
	"io"
	"math/big"
	"net"
	"strings"
	"testing"
	"time"

	"github.com/quic-go/quic-go"
)

func testCertificate(t *testing.T, expired bool) (tls.Certificate, *x509.Certificate) {
	t.Helper()
	key, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatal(err)
	}
	start, end := time.Now().Add(-time.Hour), time.Now().Add(time.Hour)
	if expired {
		start, end = time.Now().Add(-2*time.Hour), time.Now().Add(-time.Hour)
	}
	template := x509.Certificate{SerialNumber: big.NewInt(42), Subject: pkix.Name{CommonName: "observer.test"},
		DNSNames: []string{"observer.test"}, NotBefore: start, NotAfter: end,
		KeyUsage: x509.KeyUsageDigitalSignature, ExtKeyUsage: []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth}}
	der, err := x509.CreateCertificate(rand.Reader, &template, &template, key.Public(), key)
	if err != nil {
		t.Fatal(err)
	}
	leaf, err := x509.ParseCertificate(der)
	if err != nil {
		t.Fatal(err)
	}
	return tls.Certificate{Certificate: [][]byte{der}, PrivateKey: key, Leaf: leaf}, leaf
}

func TestInputAllowsOnlyBoundedPublicLiteralTargets(t *testing.T) {
	for _, ip := range []string{"1.1.1.1", "8.8.8.8", "2606:4700:4700::1111", "::ffff:8.8.8.8"} {
		body, _ := json.Marshal(request{IP: ip, Port: 443, SNI: "observer.test"})
		r, ok := parseRequest(body)
		if !ok || len(r.ALPN) != 1 || r.ALPN[0] != "h3" {
			t.Fatalf("valid input rejected: %s", ip)
		}
	}
	for _, ip := range []string{"localhost", "127.0.0.1", "10.0.0.1", "172.16.1.1", "192.168.0.1", "169.254.1.1", "100.64.0.1", "0.0.0.0", "224.0.0.1", "240.0.0.1", "192.0.2.1", "198.18.0.1", "::1", "fe80::1%lo0", "fc00::1", "ff02::1", "2001:db8::1", "::ffff:127.0.0.1"} {
		body, _ := json.Marshal(request{IP: ip, Port: 443, SNI: "observer.test"})
		if _, ok := parseRequest(body); ok {
			t.Fatalf("non-public target accepted: %s", ip)
		}
	}
}

func TestInputRejectsCredentialsUnknownFieldsTrailingJSONAndInvalidALPN(t *testing.T) {
	valid := `{"ip":"1.1.1.1","port":443,"sni":"observer.test"}`
	for _, body := range []string{
		`{"ip":"1.1.1.1","port":443,"sni":"observer.test","password":"private"}`,
		valid + valid, "null", strings.Repeat(" ", maxInput+1),
		`{"ip":"127.0.0.1","ip":"1.1.1.1","port":443,"sni":"observer.test"}`,
		`{"ip":"1.1.1.1","port":443.5,"sni":"observer.test"}`,
		`{"ip":"1.1.1.1","port":0,"sni":"observer.test"}`,
		`{"ip":"1.1.1.1","port":443,"sni":"https://secret.example"}`,
		`{"ip":"1.1.1.1","port":443,"sni":"observer.test","alpn":[""]}`,
		`{"ip":"1.1.1.1","port":443,"sni":"observer.test","alpn":["h3\nprivate"]}`,
	} {
		if _, ok := parseRequest([]byte(body)); ok {
			t.Fatal("invalid input accepted")
		}
	}
}

func TestRealQUICHandshakeCollectsSPKIWithoutAnyApplicationStream(t *testing.T) {
	certificate, leaf := testCertificate(t, false)
	sni := make(chan string, 1)
	// The observer closes as soon as the client has verified receipt of the
	// server's handshake. A regular listener can miss the server-side completion
	// before that close. Accept early so the fixture can inspect the connection
	// without requiring extra application traffic or delaying the observer.
	listener, err := quic.ListenAddrEarly("127.0.0.1:0", &tls.Config{
		Certificates: []tls.Certificate{certificate}, NextProtos: []string{"h3"},
		GetConfigForClient: func(hello *tls.ClientHelloInfo) (*tls.Config, error) { sni <- hello.ServerName; return nil, nil },
	}, &quic.Config{EnableDatagrams: true})
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	streams := make(chan error, 1)
	go func() {
		connection, err := listener.Accept(ctx)
		if err != nil {
			streams <- err
			return
		}
		if connection.ConnectionState().TLS.NegotiatedProtocol != "h3" {
			streams <- errors.New("ALPN mismatch")
			return
		}
		checks := make(chan error, 3)
		go func() {
			stream, err := connection.AcceptStream(ctx)
			if stream != nil || err == nil {
				checks <- errors.New("opened bidi stream")
			} else {
				checks <- nil
			}
		}()
		go func() {
			stream, err := connection.AcceptUniStream(ctx)
			if stream != nil || err == nil {
				checks <- errors.New("opened uni stream")
			} else {
				checks <- nil
			}
		}()
		go func() {
			data, err := connection.ReceiveDatagram(ctx)
			if len(data) > 0 || err == nil {
				checks <- errors.New("sent app datagram")
			} else {
				checks <- nil
			}
		}()
		for range 3 {
			if err := <-checks; err != nil {
				streams <- err
				return
			}
		}
		streams <- nil
	}()
	address := listener.Addr().(*net.UDPAddr)
	got := observe(ctx, request{IP: address.IP.String(), Port: address.Port, SNI: "observer.test"})
	if got.Reason != "" {
		t.Fatalf("observation failed: %s", got.Reason)
	}
	expected := sha256.Sum256(leaf.RawSubjectPublicKeyInfo)
	if got.Pin != base64.StdEncoding.EncodeToString(expected[:]) {
		t.Fatal("SPKI mismatch")
	}
	if got.NotBefore == nil || *got.NotBefore != leaf.NotBefore.Unix() || got.NotAfter == nil || *got.NotAfter != leaf.NotAfter.Unix() || got.CertificateTimeValid == nil || !*got.CertificateTimeValid {
		t.Fatal("certificate timing mismatch")
	}
	if name := <-sni; name != "observer.test" {
		t.Fatal("SNI was not preserved")
	}
	if err := <-streams; err != nil {
		t.Fatal(err)
	}
}

func TestExpiredQUICCertificateIsObservedButFlaggedInvalid(t *testing.T) {
	certificate, _ := testCertificate(t, true)
	listener, err := quic.ListenAddr("127.0.0.1:0", &tls.Config{Certificates: []tls.Certificate{certificate}, NextProtos: []string{"h3"}}, nil)
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	go listener.Accept(ctx)
	address := listener.Addr().(*net.UDPAddr)
	got := observe(ctx, request{IP: address.IP.String(), Port: address.Port, SNI: "observer.test"})
	if got.Reason != "" || got.Pin == "" || got.CertificateTimeValid == nil || *got.CertificateTimeValid {
		t.Fatal("expired certificate not explicitly marked")
	}
}

func TestRealQUICIPv6Handshake(t *testing.T) {
	certificate, leaf := testCertificate(t, false)
	listener, err := quic.ListenAddr("[::1]:0", &tls.Config{Certificates: []tls.Certificate{certificate}, NextProtos: []string{"h3"}}, nil)
	if err != nil {
		t.Skip("IPv6 loopback unavailable")
	}
	defer listener.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	go listener.Accept(ctx)
	address := listener.Addr().(*net.UDPAddr)
	got := observe(ctx, request{IP: address.IP.String(), Port: address.Port, SNI: "observer.test"})
	expected := sha256.Sum256(leaf.RawSubjectPublicKeyInfo)
	if got.Reason != "" || got.Pin != base64.StdEncoding.EncodeToString(expected[:]) {
		t.Fatal("IPv6 handshake did not return expected SPKI")
	}
}

func TestTimeoutContainsNoEndpointOrRawError(t *testing.T) {
	blackhole, err := net.ListenUDP("udp4", &net.UDPAddr{IP: net.IPv4(127, 0, 0, 1)})
	if err != nil {
		t.Fatal(err)
	}
	defer blackhole.Close()
	address := blackhole.LocalAddr().(*net.UDPAddr)
	ctx, cancel := context.WithTimeout(context.Background(), 150*time.Millisecond)
	defer cancel()
	started := time.Now()
	got := observe(ctx, request{IP: address.IP.String(), Port: address.Port, SNI: "private-secret.example"})
	encoded, _ := json.Marshal(got)
	if string(encoded) != `{"reason":"identity_timeout"}` {
		t.Fatalf("unexpected sanitized response: %s", encoded)
	}
	if time.Since(started) > time.Second {
		t.Fatal("shared deadline was not enforced")
	}
}

func TestInputReadSharesOverallDeadlineAndInvalidInputIsRedacted(t *testing.T) {
	read, write := io.Pipe()
	defer read.Close()
	defer write.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 50*time.Millisecond)
	defer cancel()
	var output bytes.Buffer
	if code := run(ctx, read, &output); code != 1 || strings.TrimSpace(output.String()) != `{"reason":"identity_timeout"}` {
		t.Fatal("input read exceeded shared deadline")
	}
	output.Reset()
	if code := run(context.Background(), strings.NewReader(`{"password":"do-not-print"}`), &output); code != 2 || strings.TrimSpace(output.String()) != `{"reason":"invalid_input"}` {
		t.Fatal("invalid input was not redacted")
	}
}

func TestRawErrorsAreMappedToFixedClasses(t *testing.T) {
	ctx := context.Background()
	for _, item := range []struct {
		err    error
		reason string
	}{
		{&quic.TransportError{ErrorCode: 0x178, ErrorMessage: "private hostname and address"}, "tls_failed"},
		{&net.OpError{Op: "dial", Net: "udp", Err: errors.New("private destination")}, "quic_unreachable"},
		{errors.New("private authentication text"), "quic_handshake_failed"},
	} {
		if got := classifyError(ctx, item.err); got != item.reason {
			t.Fatal("unexpected reason")
		}
	}
}

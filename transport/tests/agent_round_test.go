package tests

import (
	"bufio"
	"crypto/rand"
	"io"
	"net"
	"sync"
	"testing"
	"time"

	"github.com/iffiX/neutrino/transport/handshake"
	"github.com/iffiX/neutrino/transport/knock"
	"github.com/iffiX/neutrino/transport/session"
)

// heldListener accepts on loopback and keeps every connection open until
// the test ends, answering each with serve.
func heldListener(t *testing.T, serve func(net.Conn)) string {
	t.Helper()
	listener, err := net.Listen("tcp4", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	var mu sync.Mutex
	var held []net.Conn
	t.Cleanup(func() {
		listener.Close()
		mu.Lock()
		defer mu.Unlock()
		for _, conn := range held {
			conn.Close()
		}
	})
	go func() {
		for {
			conn, err := listener.Accept()
			if err != nil {
				return
			}
			mu.Lock()
			held = append(held, conn)
			mu.Unlock()
			go serve(conn)
		}
	}()
	return session.AddressScheme + listener.Addr().String()
}

// silentAddress accepts and never writes, as another network's hub does.
func silentAddress(t *testing.T) string {
	return heldListener(t, func(net.Conn) {})
}

// untrustedAddress answers a knock under hubPublic with a message 2 that no
// psk opens.
func untrustedAddress(t *testing.T, hubPublic []byte) string {
	return heldListener(t, func(conn net.Conn) {
		reader := bufio.NewReader(conn)
		header := make([]byte, knock.KnockHeaderBytes)
		if _, err := io.ReadFull(reader, header); err != nil {
			return
		}
		if _, err := knock.ReadBody(reader, header); err != nil {
			return
		}
		message2 := make([]byte, 96)
		_, _ = rand.Read(message2)
		_, _ = conn.Write(knock.EncodeHeader(hubPublic, knock.KnockTypeAnswer))
		_ = session.WriteLengthPrefixed(conn, message2)
	})
}

// TestAnAgentDialsEveryAddressAtOnce checks that an agent's join and its
// round reach the hub past a silent address listed first, with no wait for
// it.
func TestAnAgentDialsEveryAddressAtOnce(t *testing.T) {
	dir := shortTempDir(t)
	hub := startHub(t, dir, freePort(t))
	hub.records.mu.Lock()
	hub.records.tickets["ticket-agent"] = "dev-4"
	hub.records.mu.Unlock()
	agent := startAgent(t, dir, 1)
	agent.leading = []string{silentAddress(t)}

	started := time.Now()
	binding, psk := agent.join(t, hub, "ticket-agent", "dev-4")
	if elapsed := time.Since(started); elapsed > session.DialTimeout/2 {
		t.Fatalf("the join answered after %v", elapsed)
	}
	started = time.Now()
	agent.dial(t, hub, binding, psk)
	agent.hello(t, hub, binding)
	if elapsed := time.Since(started); elapsed > session.DialTimeout/2 {
		t.Fatalf("the session opened after %v", elapsed)
	}
}

// TestAJoinEndsAtAnUntrustedAnswer checks that a join's round ends with
// hub_untrusted at an answer no psk opens, with no wait for a silent
// address.
func TestAJoinEndsAtAnUntrustedAnswer(t *testing.T) {
	dir := shortTempDir(t)
	hubKey, _ := handshake.GenerateKey()
	agent := startAgent(t, dir, 1)
	addresses := []string{silentAddress(t), untrustedAddress(t, hubKey.Public)}

	started := time.Now()
	answer := agent.python.command("join", map[string]any{
		"hub_key": handshake.EncodeKey(hubKey.Public), "private_key": agent.private, "addresses": addresses,
		"ticket": "ticket-agent", "role": "agent", "protocol": knock.PROTOCOL, "machine_id": "m-dev-5",
		"name": "dev-5", "software": "neutrino_agent/0.6.0", "platform": map[string]any{"os": "linux"},
	})
	if answer["code"] != session.CodeHubUntrusted {
		t.Fatalf("join answered %v", answer)
	}
	if elapsed := time.Since(started); elapsed > session.DialTimeout/2 {
		t.Fatalf("the join answered after %v", elapsed)
	}
}

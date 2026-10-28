package knock

import (
	"bytes"
	"errors"
	"net"
	"testing"
	"time"
)

type clock struct{ now time.Time }

func (c *clock) read() time.Time { return c.now }

func testKnock(t *testing.T, hubPublic []byte) *Knock {
	t.Helper()
	raw, err := Encode([]byte("message one"), hubPublic, nil)
	if err != nil {
		t.Fatal(err)
	}
	parsed, err := Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	return parsed
}

func TestCookieReply(t *testing.T) {
	hubPublic := bytes.Repeat([]byte{0xab}, 32)
	c := &clock{now: time.Unix(1000, 0)}
	jar, err := NewCookieJar(hubPublic, c.read)
	if err != nil {
		t.Fatal(err)
	}
	address := net.ParseIP("203.0.113.9")
	first := testKnock(t, hubPublic)
	if jar.IsMac2Valid(first, address) {
		t.Fatal("a zero mac2 verifies")
	}
	reply, err := jar.Reply(first, address)
	if err != nil {
		t.Fatal(err)
	}
	header, err := ParseHeader(reply, hubPublic)
	if err != nil || len(reply) != CookieReplyBytes || header.Type != KnockTypeCookieReply {
		t.Fatalf("reply of %d bytes with header %+v: %v", len(reply), header, err)
	}
	cookie, err := OpenReply(reply, hubPublic, first.Mac1)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := OpenReply(reply, hubPublic, bytes.Repeat([]byte{1}, 16)); !errors.Is(err, ErrCookieReplyMalformed) {
		t.Fatalf("another mac1 opens the reply: %v", err)
	}
	if _, err := OpenReply(EncodeHeader(hubPublic, KnockTypeAnswer), hubPublic, first.Mac1); !errors.Is(err, ErrNotCookieReply) {
		t.Fatalf("err %v, want not a cookie reply", err)
	}
	raw, err := Encode([]byte("message one"), hubPublic, cookie)
	if err != nil {
		t.Fatal(err)
	}
	second, _ := Parse(raw)
	if !jar.IsMac2Valid(second, address) {
		t.Fatal("mac2 under the cookie does not verify")
	}
	if jar.IsMac2Valid(second, net.ParseIP("203.0.113.10")) {
		t.Fatal("the cookie verifies for another address")
	}
	mapped := net.ParseIP("::ffff:203.0.113.9")
	if !jar.IsMac2Valid(second, mapped) {
		t.Fatal("a mapped IPv4 address is not the same address")
	}
	c.now = c.now.Add(CookieSecretLifetime - time.Second)
	if !jar.IsMac2Valid(second, address) {
		t.Fatal("the cookie stopped verifying before its lifetime")
	}
	c.now = c.now.Add(time.Second)
	if jar.IsMac2Valid(second, address) {
		t.Fatal("a cookie under the previous secret verifies")
	}
}

func TestLedger(t *testing.T) {
	ledger := NewKnockLedger()
	now := time.Unix(0, 0)
	var entries []*Unadmitted
	for i := 0; i < UnadmittedMax; i++ {
		entry, victim := ledger.Accept(now.Add(time.Duration(i) * time.Second))
		if victim != nil {
			t.Fatalf("a victim at %d connections", i+1)
		}
		entries = append(entries, entry)
	}
	ledger.HandshakeDone(entries[0])
	newest, victim := ledger.Accept(now.Add(time.Hour))
	if victim != entries[1] {
		t.Fatal("the oldest connection without a handshake was not chosen")
	}
	if ledger.Waiting() != UnadmittedMax {
		t.Fatalf("%d waiting", ledger.Waiting())
	}
	for _, entry := range append(entries[2:], newest) {
		ledger.HandshakeDone(entry)
	}
	_, victim = ledger.Accept(now.Add(2 * time.Hour))
	if victim != entries[0] {
		t.Fatal("the oldest of all was not chosen once every handshake is done")
	}
	ledger.Leave(entries[2])
	ledger.Leave(entries[2])
	if ledger.Waiting() != UnadmittedMax-1 {
		t.Fatalf("%d waiting after a leave", ledger.Waiting())
	}

	for i := 0; i < HandshakesInFlightMax; i++ {
		if !ledger.BeginHandshake() {
			t.Fatalf("handshake %d refused", i+1)
		}
		if ledger.IsUnderLoad() != (i+1 > CookieLoadThreshold) {
			t.Fatalf("under load %v at %d in flight", ledger.IsUnderLoad(), i+1)
		}
	}
	if ledger.BeginHandshake() {
		t.Fatal("a handshake past the limit was counted")
	}
	ledger.EndHandshake()
	if !ledger.BeginHandshake() {
		t.Fatal("a handshake after one ended was refused")
	}
}

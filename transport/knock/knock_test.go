package knock

import (
	"bytes"
	"encoding/hex"
	"errors"
	"testing"
)

type vectors struct {
	HubPublic string
	Message1  string
	Mac1Key   string
	Mac1      string
	Cookie    string
	Mac2      string
	Knock     string
}

func loadVectors(t *testing.T) vectors {
	t.Helper()
	return knockVectors
}

func unhex(t *testing.T, text string) []byte {
	t.Helper()
	data, err := hex.DecodeString(text)
	if err != nil {
		t.Fatal(err)
	}
	return data
}

func TestVectors(t *testing.T) {
	v := loadVectors(t)
	hubPublic := unhex(t, v.HubPublic)
	message1 := unhex(t, v.Message1)
	cookie := unhex(t, v.Cookie)
	if got := hex.EncodeToString(Mac1Key(hubPublic)); got != v.Mac1Key {
		t.Fatalf("mac1 key %s, want %s", got, v.Mac1Key)
	}
	raw, err := Encode(message1, hubPublic, cookie)
	if err != nil {
		t.Fatal(err)
	}
	if got := hex.EncodeToString(raw); got != v.Knock {
		t.Fatalf("knock %s, want %s", got, v.Knock)
	}
	parsed, err := Parse(raw)
	if err != nil {
		t.Fatal(err)
	}
	if got := hex.EncodeToString(parsed.Mac1); got != v.Mac1 {
		t.Fatalf("mac1 %s, want %s", got, v.Mac1)
	}
	if got := hex.EncodeToString(parsed.Mac2); got != v.Mac2 {
		t.Fatalf("mac2 %s, want %s", got, v.Mac2)
	}
	if !parsed.VerifyMac1(hubPublic) || !parsed.VerifyMac2(cookie) {
		t.Fatal("the macs do not verify")
	}
	if !bytes.Equal(parsed.Message1, message1) {
		t.Fatal("message 1 differs")
	}
	noCookie, err := Encode(message1, hubPublic, nil)
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(noCookie[len(noCookie)-KnockMacBytes:], make([]byte, KnockMacBytes)) {
		t.Fatal("mac2 without a cookie is not zero")
	}
	fromReader, err := ReadBody(bytes.NewReader(raw[1:]))
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(fromReader.Raw, raw) {
		t.Fatal("the knock read differs from the one encoded")
	}
}

func TestWrongKnocks(t *testing.T) {
	v := loadVectors(t)
	raw := unhex(t, v.Knock)
	otherKey := unhex(t, v.Mac1Key)
	wrongVersion := append([]byte{5}, raw[1:]...)
	wrongLength := append([]byte{}, raw...)
	wrongLength[2]++
	short := raw[:KnockHeaderBytes+KnockMacBytes]
	wrongMac1 := append([]byte{}, raw...)
	wrongMac1[len(raw)-2*KnockMacBytes] ^= 1
	tooLong := make([]byte, KnockBytesMax+1)
	tooLong[0] = KnockVersion
	tooLongLength := KnockBytesMax + 1 - KnockHeaderBytes - 2*KnockMacBytes
	tooLong[1] = byte(tooLongLength >> 8)
	tooLong[2] = byte(tooLongLength)
	cases := []struct {
		name string
		raw  []byte
	}{
		{"version", wrongVersion},
		{"length", wrongLength},
		{"short", short},
		{"too long", tooLong},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			if _, err := Parse(c.raw); !errors.Is(err, ErrKnockMalformed) {
				t.Fatalf("err %v, want malformed", err)
			}
		})
	}
	parsed, err := Parse(wrongMac1)
	if err != nil {
		t.Fatal(err)
	}
	if parsed.VerifyMac1(unhex(t, v.HubPublic)) {
		t.Fatal("a changed mac1 verifies")
	}
	good, _ := Parse(raw)
	if good.VerifyMac1(otherKey) {
		t.Fatal("mac1 verifies under another key")
	}
	if _, err := ReadBody(bytes.NewReader([]byte{0x03, 0xff})); !errors.Is(err, ErrKnockMalformed) {
		t.Fatalf("err %v, want malformed", err)
	}
	if _, err := Encode(make([]byte, KnockBytesMax), nil, nil); !errors.Is(err, ErrKnockMalformed) {
		t.Fatalf("err %v, want malformed", err)
	}
}

func TestPayload(t *testing.T) {
	data := Payload{Protocol: PROTOCOL, Role: KnockRoleClient, IsJoin: true, Time: 1234}.Marshal()
	if string(data) != `{"protocol":4,"role":"client","is_join":true,"time":1234}` {
		t.Fatalf("payload %s", data)
	}
	payload, err := ParsePayload(data)
	if err != nil || payload.Time != 1234 || !payload.IsJoin {
		t.Fatalf("parse: %+v %v", payload, err)
	}
	for _, bad := range []string{`{"role":"hub"}`, `nope`, ``} {
		if _, err := ParsePayload([]byte(bad)); !errors.Is(err, ErrKnockMalformed) {
			t.Fatalf("%q: %v", bad, err)
		}
	}
}

func TestReplayWindow(t *testing.T) {
	window := NewReplayWindow(2)
	a := bytes.Repeat([]byte{1}, 32)
	b := bytes.Repeat([]byte{2}, 32)
	c := bytes.Repeat([]byte{3}, 32)
	cases := []struct {
		name string
		key  []byte
		time int64
		want bool
	}{
		{"the first knock of a key", a, 10, true},
		{"the same time again", a, 10, false},
		{"an earlier time", a, 9, false},
		{"a later time", a, 11, true},
		{"another key with an earlier time", b, 5, true},
		{"a third key pushes the one used longest ago out", c, 1, true},
		{"the pushed-out key starts afresh", a, 1, true},
	}
	for _, step := range cases {
		if got := window.Accept(step.key, step.time); got != step.want {
			t.Fatalf("%s: %v, want %v", step.name, got, step.want)
		}
	}
	if window.Len() != 2 {
		t.Fatalf("window holds %d keys", window.Len())
	}
}

package handshake

import (
	"bytes"
	"encoding/hex"
	"errors"
	"testing"

	"github.com/flynn/noise"
)

type vector struct {
	InitStatic     string
	RespStatic     string
	InitEphemeral  string
	RespEphemeral  string
	PresharedKey   string
	Msg0Payload    string
	Msg0Ciphertext string
	Msg1Payload    string
	Msg1Ciphertext string
	Msg2Payload    string
	Msg2Ciphertext string
	Msg3Payload    string
	Msg3Ciphertext string
}

func unhex(t *testing.T, text string) []byte {
	t.Helper()
	data, err := hex.DecodeString(text)
	if err != nil {
		t.Fatal(err)
	}
	return data
}

func pairFromPrivate(t *testing.T, privateHex string) noise.DHKey {
	t.Helper()
	pair, err := KeyFromPrivate(privateHex)
	if err != nil {
		t.Fatal(err)
	}
	return pair
}

func TestVector(t *testing.T) {
	v := cacophonyVector
	initStatic := pairFromPrivate(t, v.InitStatic)
	respStatic := pairFromPrivate(t, v.RespStatic)
	psk := unhex(t, v.PresharedKey)

	initiator, err := newInitiator(initStatic, unhex(t, v.InitEphemeral), respStatic.Public, psk, unhex(t, v.Msg0Payload), nil)
	if err != nil {
		t.Fatal(err)
	}
	if got := hex.EncodeToString(initiator.Message1); got != v.Msg0Ciphertext {
		t.Fatalf("message 1 %s, want %s", got, v.Msg0Ciphertext)
	}
	responder, err := newResponder(respStatic, bytes.NewReader(unhex(t, v.RespEphemeral)), nil)
	if err != nil {
		t.Fatal(err)
	}
	if err := responder.Read(initiator.Message1); err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(responder.PeerStatic, initStatic.Public) {
		t.Fatalf("peer static %x, want %x", responder.PeerStatic, initStatic.Public)
	}
	message2, hubKeys, err := responder.Answer(psk, nil)
	if err != nil {
		t.Fatal(err)
	}
	if got := hex.EncodeToString(message2); got != v.Msg1Ciphertext {
		t.Fatalf("message 2 %s, want %s", got, v.Msg1Ciphertext)
	}
	peerKeys, isRefusal, err := initiator.Open(message2)
	if err != nil || isRefusal {
		t.Fatalf("open: %v, refusal %v", err, isRefusal)
	}
	sealed, err := peerKeys.Send.Encrypt(nil, nil, unhex(t, v.Msg2Payload))
	if err != nil {
		t.Fatal(err)
	}
	if got := hex.EncodeToString(sealed); got != v.Msg2Ciphertext {
		t.Fatalf("transport message 1 %s, want %s", got, v.Msg2Ciphertext)
	}
	if _, err := hubKeys.Receive.Decrypt(nil, nil, sealed); err != nil {
		t.Fatal(err)
	}
	sealed, err = hubKeys.Send.Encrypt(nil, nil, unhex(t, v.Msg3Payload))
	if err != nil {
		t.Fatal(err)
	}
	if got := hex.EncodeToString(sealed); got != v.Msg3Ciphertext {
		t.Fatalf("transport message 2 %s, want %s", got, v.Msg3Ciphertext)
	}
}

// TestPaddedVector checks message 1 and message 2 with their padding against
// paddedVector, and that each side reads the other's message through it.
func TestPaddedVector(t *testing.T) {
	v := cacophonyVector
	initStatic := pairFromPrivate(t, v.InitStatic)
	respStatic := pairFromPrivate(t, v.RespStatic)
	psk := unhex(t, v.PresharedKey)
	payload := append([]byte(paddedVector.Payload), bytes.Repeat([]byte{paddedVector.Padding1}, paddedVector.PaddingBytes)...)
	initiator, err := newInitiator(initStatic, unhex(t, v.InitEphemeral), respStatic.Public, psk, payload, []byte(HandshakePrologue))
	if err != nil {
		t.Fatal(err)
	}
	if got := hex.EncodeToString(initiator.Message1); got != paddedVector.Message1 {
		t.Fatalf("message 1 %s, want %s", got, paddedVector.Message1)
	}
	responder, err := newResponder(respStatic, bytes.NewReader(unhex(t, v.RespEphemeral)), []byte(HandshakePrologue))
	if err != nil {
		t.Fatal(err)
	}
	if err := responder.Read(initiator.Message1); err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(responder.Payload, payload) {
		t.Fatalf("payload %q", responder.Payload)
	}
	message2, _, err := responder.Answer(psk, bytes.Repeat([]byte{paddedVector.Padding2}, paddedVector.PaddingBytes))
	if err != nil {
		t.Fatal(err)
	}
	if got := hex.EncodeToString(message2); got != paddedVector.Message2 {
		t.Fatalf("message 2 %s, want %s", got, paddedVector.Message2)
	}
	if _, isRefusal, err := initiator.Open(message2); err != nil || isRefusal {
		t.Fatalf("open: %v, refusal %v", err, isRefusal)
	}
}

func TestPskRules(t *testing.T) {
	hub, err := GenerateKey()
	if err != nil {
		t.Fatal(err)
	}
	peer, err := GenerateKey()
	if err != nil {
		t.Fatal(err)
	}
	token := bytes.Repeat([]byte{7}, HandshakeKeyBytes)
	other := bytes.Repeat([]byte{9}, HandshakeKeyBytes)
	cases := []struct {
		name       string
		peerPsk    []byte
		hubPsk     []byte
		isRefusal  bool
		wantOpened bool
	}{
		{"a join under the zero psk", ZeroPsk, ZeroPsk, false, true},
		{"a bound peer under its token", token, token, false, true},
		{"a refusal under the zero psk opened by the second try", token, ZeroPsk, true, true},
		{"another token opens under neither", token, other, false, false},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			initiator, err := NewInitiator(peer, hub.Public, c.peerPsk, []byte(`{"role":"agent"}`))
			if err != nil {
				t.Fatal(err)
			}
			responder, err := NewResponder(hub)
			if err != nil {
				t.Fatal(err)
			}
			if err := responder.Read(initiator.Message1); err != nil {
				t.Fatal(err)
			}
			if string(responder.Payload) != `{"role":"agent"}` {
				t.Fatalf("payload %q", responder.Payload)
			}
			message2, hubKeys, err := responder.Answer(c.hubPsk, nil)
			if err != nil {
				t.Fatal(err)
			}
			if len(message2) != HandshakeMessage2Bytes {
				t.Fatalf("message 2 is %d bytes", len(message2))
			}
			peerKeys, isRefusal, err := initiator.Open(message2)
			if !c.wantOpened {
				if !errors.Is(err, ErrHubUntrusted) {
					t.Fatalf("err %v, want hub untrusted", err)
				}
				return
			}
			if err != nil {
				t.Fatal(err)
			}
			if isRefusal != c.isRefusal {
				t.Fatalf("refusal %v, want %v", isRefusal, c.isRefusal)
			}
			sealed, err := hubKeys.Send.Encrypt(nil, nil, []byte("refused"))
			if err != nil {
				t.Fatal(err)
			}
			plain, err := peerKeys.Receive.Decrypt(nil, nil, sealed)
			if err != nil || string(plain) != "refused" {
				t.Fatalf("decrypt: %q %v", plain, err)
			}
		})
	}
}

func TestMessage1UnderAnotherHubKey(t *testing.T) {
	hub, _ := GenerateKey()
	otherHub, _ := GenerateKey()
	peer, _ := GenerateKey()
	initiator, err := NewInitiator(peer, otherHub.Public, ZeroPsk, nil)
	if err != nil {
		t.Fatal(err)
	}
	responder, _ := NewResponder(hub)
	if err := responder.Read(initiator.Message1); !errors.Is(err, ErrMessage1Invalid) {
		t.Fatalf("err %v, want message 1 invalid", err)
	}
}

func TestKeyText(t *testing.T) {
	pair, err := GenerateKey()
	if err != nil {
		t.Fatal(err)
	}
	again, err := KeyFromPrivate(EncodeKey(pair.Private))
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(again.Public, pair.Public) {
		t.Fatal("public key differs")
	}
	for _, bad := range []string{"", "zz", EncodeKey(pair.Private)[:62]} {
		if _, err := DecodeKey(bad); !errors.Is(err, ErrKeyInvalid) {
			t.Fatalf("%q: %v", bad, err)
		}
	}
}

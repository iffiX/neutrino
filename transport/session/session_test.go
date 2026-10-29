package session

import (
	"bufio"
	"context"
	"crypto/rand"
	"errors"
	"io"
	"net"
	"sync/atomic"
	"testing"
	"time"

	"github.com/libp2p/go-yamux/v4"

	"github.com/iffiX/neutrino/transport/handshake"
)

// noisePair joins two Noise connections over a pipe through a real handshake.
func noisePair(t *testing.T) (*NoiseConn, *NoiseConn) {
	t.Helper()
	hub, _ := handshake.GenerateKey()
	peer, _ := handshake.GenerateKey()
	initiator, err := handshake.NewInitiator(peer, hub.Public, handshake.ZeroPsk, nil)
	if err != nil {
		t.Fatal(err)
	}
	responder, _ := handshake.NewResponder(hub)
	if err := responder.Read(initiator.Message1); err != nil {
		t.Fatal(err)
	}
	message2, hubKeys, err := responder.Answer(handshake.ZeroPsk, nil)
	if err != nil {
		t.Fatal(err)
	}
	peerKeys, _, err := initiator.Open(message2)
	if err != nil {
		t.Fatal(err)
	}
	near, far := net.Pipe()
	return NewNoiseConn(near, bufio.NewReaderSize(near, 2*NoiseMessageMax), peerKeys),
		NewNoiseConn(far, bufio.NewReaderSize(far, 2*NoiseMessageMax), hubKeys)
}

func TestNoiseConnCarriesBytes(t *testing.T) {
	peer, hub := noisePair(t)
	payload := make([]byte, 3*NoisePlainMax+17)
	_, _ = rand.Read(payload)
	go func() {
		_, _ = peer.Write(payload)
	}()
	got := make([]byte, len(payload))
	if _, err := io.ReadFull(hub, got); err != nil {
		t.Fatal(err)
	}
	if string(got) != string(payload) {
		t.Fatal("the bytes differ")
	}
	if err := WriteLengthPrefixed(io.Discard, make([]byte, NoiseMessageMax+1)); !errors.Is(err, ErrNoiseMessageTooLarge) {
		t.Fatalf("%v", err)
	}
}

func TestSessionSettings(t *testing.T) {
	c := config(DefaultTimings)
	if err := yamux.VerifyConfig(c); err != nil {
		t.Fatal(err)
	}
	if c.MaxMessageSize != NoisePlainMax || c.InitialStreamWindowSize != StreamWindowInitialBytes || c.MaxStreamWindowSize != StreamWindowMaxBytes {
		t.Fatalf("windows %d %d %d", c.MaxMessageSize, c.InitialStreamWindowSize, c.MaxStreamWindowSize)
	}
	if !c.EnableKeepAlive || c.KeepAliveInterval != KeepAliveInterval || c.ConnectionWriteTimeout != KeepAliveTimeout {
		t.Fatalf("keepalive %v %v", c.KeepAliveInterval, c.ConnectionWriteTimeout)
	}
}

func TestSessionStreamsAndMemoryCap(t *testing.T) {
	peerConn, hubConn := noisePair(t)
	limit := int64(StreamWindowInitialBytes + StreamWindowInitialBytes/2)
	memory := NewTransportMemory(limit)
	var refused atomic.Int32
	hub, err := NewHubSession(hubConn, memory, DefaultTimings, func() { refused.Add(1) })
	if err != nil {
		t.Fatal(err)
	}
	peer, err := NewPeerSession(peerConn, DefaultTimings)
	if err != nil {
		t.Fatal(err)
	}
	defer hub.Close()
	defer peer.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	accepted := make(chan *yamux.Stream, 4)
	go func() {
		for {
			stream, err := hub.AcceptStream()
			if err != nil {
				return
			}
			accepted <- stream
		}
	}()

	first, err := peer.OpenStream(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if first.StreamID()%2 != 1 {
		t.Fatalf("the peer's stream id %d is even", first.StreamID())
	}
	go func() {
		_, _ = first.Write([]byte("hello"))
	}()
	hubFirst := <-accepted
	buffer := make([]byte, 5)
	if _, err := io.ReadFull(hubFirst, buffer); err != nil || string(buffer) != "hello" {
		t.Fatalf("read %q %v", buffer, err)
	}

	payload := make([]byte, 4*StreamWindowInitialBytes)
	go func() {
		_, _ = first.Write(payload)
	}()
	if _, err := io.ReadFull(hubFirst, payload); err != nil {
		t.Fatal(err)
	}
	if memory.Used() > limit {
		t.Fatalf("the window grew past the cap: %d", memory.Used())
	}

	second, err := peer.OpenStream(ctx)
	if err != nil {
		t.Fatal(err)
	}
	go func() {
		_, _ = second.Write([]byte("more"))
	}()
	second.SetReadDeadline(time.Now().Add(3 * time.Second))
	if _, err := second.Read(buffer); !errors.Is(err, yamux.ErrStreamReset) {
		t.Fatalf("a stream past the cap was not reset: %v", err)
	}
	if _, err := hub.OpenStream(ctx); !errors.Is(err, ErrMemoryExhausted) {
		t.Fatalf("the hub's stream past the cap: %v", err)
	}
	reported := time.Now().Add(3 * time.Second)
	for refused.Load() != 2 {
		if time.Now().After(reported) {
			t.Fatalf("%d refusals reported, want 2", refused.Load())
		}
		time.Sleep(10 * time.Millisecond)
	}
	select {
	case stream := <-accepted:
		t.Fatalf("stream %d past the cap was accepted", stream.StreamID())
	default:
	}

	go func() {
		_, _ = first.Write([]byte("again"))
	}()
	if _, err := io.ReadFull(hubFirst, buffer); err != nil || string(buffer) != "again" {
		t.Fatalf("the first stream after the refusals read %q %v", buffer, err)
	}
	go func() {
		_, _ = hubFirst.Write([]byte("reply"))
	}()
	if _, err := io.ReadFull(first, buffer); err != nil || string(buffer) != "reply" {
		t.Fatalf("the first stream's reply read %q %v", buffer, err)
	}
	deadline := time.Now().Add(3 * time.Second)
	for hub.NumStreams() != 1 || memory.Used() > limit {
		if time.Now().After(deadline) {
			t.Fatalf("%d streams and %d bytes held after the refusals", hub.NumStreams(), memory.Used())
		}
		time.Sleep(10 * time.Millisecond)
	}
	if hub.IsClosed() || peer.IsClosed() {
		t.Fatal("a refusal at the cap ended the session")
	}
}

func TestKeepAliveClosesASilentSession(t *testing.T) {
	near, far := net.Pipe()
	go func() {
		_, _ = io.Copy(io.Discard, far)
	}()
	peer, err := NewPeerSession(near, Timings{KeepAliveInterval: 50 * time.Millisecond, KeepAliveTimeout: 200 * time.Millisecond})
	if err != nil {
		t.Fatal(err)
	}
	select {
	case <-peer.CloseChan():
	case <-time.After(5 * time.Second):
		t.Fatal("the silent session stayed open")
	}
	if !peer.IsClosed() {
		t.Fatal("the session does not read as closed")
	}
	far.Close()
}

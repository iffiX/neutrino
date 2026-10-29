package tests

import (
	"crypto/sha256"
	"encoding/hex"
	"testing"
	"time"

	"github.com/iffiX/neutrino/transport/relay"
	"github.com/iffiX/neutrino/transport/session"
)

// bind writes a peer's binding into the faked hub Python's records and
// returns the psk of its token.
func (h *hubSide) bind(peer *peerSide, id string) string {
	sum := sha256.Sum256([]byte("token-" + id))
	psk := hex.EncodeToString(sum[:])
	h.records.mu.Lock()
	h.records.bindings[peer.key] = map[string]any{"id": id, "role": peer.role, "psk": psk}
	h.records.mu.Unlock()
	return psk
}

// TestControlUnavailableIsDialledAgainInFiveSeconds checks that an agent
// and a client refused control_unavailable while the hub's Python is away
// dial again 5 seconds later, and that both are admitted within 5 seconds
// of the Python's return.
func TestControlUnavailableIsDialledAgainInFiveSeconds(t *testing.T) {
	dir := shortTempDir(t)
	hub := startHubAway(t, dir, freePort(t), nil)
	agent := startAgent(t, dir, 1)
	client := startClient(t, dir)
	agent.dial(t, hub, "dev-8", hub.bind(agent, "dev-8"))
	client.dial(t, hub, "cl-8", hub.bind(client, "cl-8"))

	retry := relay.RelayControlRetryAfter
	results := make(chan roundEnds, 2)
	for _, peer := range []*peerSide{agent, client} {
		go func(peer *peerSide) { results <- twoRoundEnds(peer) }(peer)
	}
	for range 2 {
		ended := <-results
		if len(ended.times) != 2 {
			t.Fatalf("%s round ends %v", ended.role, ended.events)
		}
		for _, roundEnd := range ended.events {
			params, _ := roundEnd["params"].(map[string]any)
			if roundEnd["code"] != session.CodeControlUnavailable || roundEnd["next_round_s"] != retry.Seconds() || params["retry_after_s"] != retry.Seconds() {
				t.Fatalf("%s round_end %v", ended.role, roundEnd)
			}
		}
		if gap := ended.times[1].Sub(ended.times[0]); gap < retry || gap > retry+time.Second {
			t.Fatalf("%s dialled again after %v", ended.role, gap)
		}
	}

	hub.connectPython(t)
	returned := time.Now()
	agent.hello(t, hub, "dev-8")
	client.hello(t, hub, "cl-8")
	if elapsed := time.Since(returned); elapsed > retry+time.Second {
		t.Fatalf("both were admitted %v after the Python's return", elapsed)
	}
}

// roundEnds are the first two round_end events of a peer and when each
// arrived.
type roundEnds struct {
	role   string
	events []map[string]any
	times  []time.Time
}

// twoRoundEnds reads a peer's events until its second round_end, or for
// 20 seconds.
func twoRoundEnds(peer *peerSide) roundEnds {
	ended := roundEnds{role: peer.role}
	deadline := time.After(20 * time.Second)
	for len(ended.times) < 2 {
		select {
		case event := <-peer.python.events:
			if event["event"] == "round_end" {
				ended.events = append(ended.events, event)
				ended.times = append(ended.times, time.Now())
			}
		case <-deadline:
			return ended
		}
	}
	return ended
}

package tests

import (
	"crypto/sha256"
	"encoding/hex"
	"slices"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/iffiX/neutrino/transport/relay"
	"github.com/iffiX/neutrino/transport/session"
)

// hubLines records a hub transport's log lines, each a verb and its
// key=value pairs.
type hubLines struct {
	mu    sync.Mutex
	lines []string
}

func (l *hubLines) add(verb string, fields ...string) {
	line := verb
	for i := 0; i+1 < len(fields); i += 2 {
		line += " " + fields[i] + "=" + fields[i+1]
	}
	l.mu.Lock()
	defer l.mu.Unlock()
	l.lines = append(l.lines, line)
}

// named returns the lines of the verbs given, in the order written.
func (l *hubLines) named(verbs ...string) []string {
	l.mu.Lock()
	defer l.mu.Unlock()
	var found []string
	for _, line := range l.lines {
		verb, _, _ := strings.Cut(line, " ")
		if slices.Contains(verbs, verb) {
			found = append(found, line)
		}
	}
	return found
}

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
// dial again 5 seconds later, that both are admitted within 5 seconds of
// the Python's return, and that the hub writes one refusal line for the
// run and one at its end.
func TestControlUnavailableIsDialledAgainInFiveSeconds(t *testing.T) {
	dir := shortTempDir(t)
	lines := &hubLines{}
	hub := startHubAway(t, dir, freePort(t), lines.add)
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
	got := lines.named("refused", "refusals_ended")
	if len(got) != 2 || !strings.HasPrefix(got[0], "refused address=127.0.0.1 code=control_unavailable count=1") || !strings.HasPrefix(got[1], "refusals_ended code=control_unavailable count=") {
		t.Fatalf("lines %q", got)
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

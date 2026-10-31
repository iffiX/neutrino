package control

import (
	"sync"
	"testing"
)

// Streams announced at the same instant each wait under an id of their own.
func TestStreamsAnnouncedAtOnceWaitUnderDistinctIDs(t *testing.T) {
	base := newPeerBase(nil, testSecret, nil)
	const callers, each = 16, 200
	ids := make(chan string, callers*each)
	var wg sync.WaitGroup
	for i := 0; i < callers; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for j := 0; j < each; j++ {
				ids <- base.newStreamID()
			}
		}()
	}
	wg.Wait()
	close(ids)
	seen := make(map[string]bool)
	for id := range ids {
		if seen[id] {
			t.Fatalf("stream id %s handed out twice", id)
		}
		seen[id] = true
	}
	if len(seen) != callers*each {
		t.Fatalf("got %d ids, want %d", len(seen), callers*each)
	}
}

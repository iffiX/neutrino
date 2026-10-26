package knock

import (
	"container/list"
	"sync"
)

// ReplayWindow keeps, for each static key it accepted a knock from, the
// latest time it accepted, for at most a fixed number of keys, the one used
// longest ago giving way.
type ReplayWindow struct {
	max int

	// mu guards entries and order.
	mu      sync.Mutex
	entries map[[32]byte]*list.Element
	order   *list.List
}

type replayEntry struct {
	key  [32]byte
	time int64
}

// NewReplayWindow makes a window remembering at most max keys.
func NewReplayWindow(max int) *ReplayWindow {
	return &ReplayWindow{max: max, entries: make(map[[32]byte]*list.Element), order: list.New()}
}

// Accept reports whether a knock from publicKey at time is later than the
// last one accepted for that key, and records it when it is. The first knock
// of a key is accepted.
func (w *ReplayWindow) Accept(publicKey []byte, time int64) bool {
	var key [32]byte
	copy(key[:], publicKey)
	w.mu.Lock()
	defer w.mu.Unlock()
	if element, ok := w.entries[key]; ok {
		entry := element.Value.(*replayEntry)
		if time <= entry.time {
			return false
		}
		entry.time = time
		w.order.MoveToFront(element)
		return true
	}
	if w.order.Len() >= w.max {
		oldest := w.order.Back()
		delete(w.entries, oldest.Value.(*replayEntry).key)
		w.order.Remove(oldest)
	}
	w.entries[key] = w.order.PushFront(&replayEntry{key: key, time: time})
	return true
}

// Len is the number of keys the window holds.
func (w *ReplayWindow) Len() int {
	w.mu.Lock()
	defer w.mu.Unlock()
	return w.order.Len()
}

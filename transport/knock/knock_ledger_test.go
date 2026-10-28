package knock

import (
	"testing"
	"time"
)

// TestLedgerClosesRefusedFirst checks the order at UnadmittedMax: a refused
// connection first, the oldest of them, before any handshake in progress.
func TestLedgerClosesRefusedFirst(t *testing.T) {
	ledger := NewKnockLedger()
	now := time.Unix(0, 0)
	var entries []*Unadmitted
	for i := 0; i < UnadmittedMax; i++ {
		entry, _ := ledger.Accept(now.Add(time.Duration(i) * time.Second))
		entries = append(entries, entry)
	}
	ledger.Refuse(entries[90])
	ledger.Refuse(entries[40])
	ledger.HandshakeDone(entries[10])
	_, victim := ledger.Accept(now.Add(time.Hour))
	if victim != entries[40] {
		t.Fatal("the oldest refused connection was not chosen first")
	}
	_, victim = ledger.Accept(now.Add(2 * time.Hour))
	if victim != entries[90] {
		t.Fatal("the second refused connection was not chosen next")
	}
	_, victim = ledger.Accept(now.Add(3 * time.Hour))
	if victim != entries[0] {
		t.Fatal("the oldest connection in its handshake was not chosen once none is refused")
	}
}

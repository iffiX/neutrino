package knock

import (
	"sync"
	"time"
)

// Unadmitted is one connection that has not passed hello, as the ledger
// counts it.
type Unadmitted struct {
	acceptedAt      time.Time
	isHandshakeDone bool
	isRefused       bool
	isListed        bool
}

// KnockLedger counts the connections waiting for admission and the knocks
// in flight, and applies the limits on both.
type KnockLedger struct {
	// mu guards waiting and inFlight.
	mu       sync.Mutex
	waiting  []*Unadmitted
	inFlight int
}

// NewKnockLedger makes an empty ledger.
func NewKnockLedger() *KnockLedger {
	return &KnockLedger{}
}

// Accept counts a connection accepted at now. When the count passes
// UnadmittedMax it returns the earlier connection to close to make room: the
// oldest refused, else the oldest whose handshake is not done, else the
// oldest of all; otherwise nil.
func (l *KnockLedger) Accept(now time.Time) (*Unadmitted, *Unadmitted) {
	l.mu.Lock()
	defer l.mu.Unlock()
	entry := &Unadmitted{acceptedAt: now, isListed: true}
	l.waiting = append(l.waiting, entry)
	if len(l.waiting) <= UnadmittedMax {
		return entry, nil
	}
	earlier := l.waiting[:len(l.waiting)-1]
	victim := earlier[0]
	for _, candidate := range earlier {
		if candidate.evictionRank() < victim.evictionRank() {
			victim = candidate
		}
	}
	l.removeLocked(victim)
	return entry, victim
}

// Refuse marks a connection the door refused and keeps open until its
// deadline.
func (l *KnockLedger) Refuse(entry *Unadmitted) {
	l.mu.Lock()
	defer l.mu.Unlock()
	entry.isRefused = true
}

// HandshakeDone marks a connection whose message 2 is written.
func (l *KnockLedger) HandshakeDone(entry *Unadmitted) {
	l.mu.Lock()
	defer l.mu.Unlock()
	entry.isHandshakeDone = true
}

// Leave takes a connection out of the unadmitted count: it was admitted or
// it closed.
func (l *KnockLedger) Leave(entry *Unadmitted) {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.removeLocked(entry)
}

// BeginHandshake counts a knock whose message 1 is about to be opened. It
// returns false, counting nothing, at HandshakesInFlightMax.
func (l *KnockLedger) BeginHandshake() bool {
	l.mu.Lock()
	defer l.mu.Unlock()
	if l.inFlight >= HandshakesInFlightMax {
		return false
	}
	l.inFlight++
	return true
}

// EndHandshake uncounts a knock whose answer is written or that failed.
func (l *KnockLedger) EndHandshake() {
	l.mu.Lock()
	defer l.mu.Unlock()
	l.inFlight--
}

// IsUnderLoad reports whether more than CookieLoadThreshold knocks are in
// flight.
func (l *KnockLedger) IsUnderLoad() bool {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.inFlight > CookieLoadThreshold
}

// Waiting is the number of connections that have not passed hello.
func (l *KnockLedger) Waiting() int {
	l.mu.Lock()
	defer l.mu.Unlock()
	return len(l.waiting)
}

// InFlight is the number of knocks in flight.
func (l *KnockLedger) InFlight() int {
	l.mu.Lock()
	defer l.mu.Unlock()
	return l.inFlight
}

func (l *KnockLedger) removeLocked(entry *Unadmitted) {
	if !entry.isListed {
		return
	}
	entry.isListed = false
	for i, candidate := range l.waiting {
		if candidate == entry {
			l.waiting = append(l.waiting[:i], l.waiting[i+1:]...)
			return
		}
	}
}

// evictionRank orders connections for closing at UnadmittedMax: a refused
// one first, then one whose handshake is not done, then the rest. The
// caller locks the ledger first.
func (u *Unadmitted) evictionRank() int {
	switch {
	case u.isRefused:
		return 0
	case !u.isHandshakeDone:
		return 1
	}
	return 2
}

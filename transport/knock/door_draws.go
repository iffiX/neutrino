package knock

import (
	"math/rand/v2"
	"time"
)

// DoorDraws are the door's two random draws for each connection.
type DoorDraws struct {
	// ReadBytes is how far the door reads a connection before it refuses it.
	ReadBytes func() int
	// Hold is how long after the accept a refused connection is held.
	Hold func() time.Duration
}

// DefaultDoorDraws draws both uniformly within their constants' bounds.
var DefaultDoorDraws = DoorDraws{ReadBytes: DrawReadBytes, Hold: DrawHold}

// DrawReadBytes returns a length from DoorReadBytesMin to DoorReadBytesMax.
func DrawReadBytes() int {
	return DoorReadBytesMin + rand.IntN(DoorReadBytesMax-DoorReadBytesMin+1)
}

// DrawHold returns a duration from DoorHoldMin to DoorHoldMax.
func DrawHold() time.Duration {
	return DoorHoldMin + rand.N(DoorHoldMax-DoorHoldMin+1)
}

package knock

import (
	"testing"
	"time"
)

// TestDrawsStayInTheirRanges checks both draws over many connections: each
// within its bounds, and the bounds themselves drawn or nearly.
func TestDrawsStayInTheirRanges(t *testing.T) {
	smallest, largest := DoorReadBytesMax, DoorReadBytesMin
	shortest, longest := DoorHoldMax, DoorHoldMin
	for i := 0; i < 20000; i++ {
		readBytes := DrawReadBytes()
		if readBytes < DoorReadBytesMin || readBytes > DoorReadBytesMax {
			t.Fatalf("read length %d", readBytes)
		}
		smallest, largest = min(smallest, readBytes), max(largest, readBytes)
		hold := DrawHold()
		if hold < DoorHoldMin || hold > DoorHoldMax {
			t.Fatalf("hold %v", hold)
		}
		shortest, longest = min(shortest, hold), max(longest, hold)
	}
	if smallest != DoorReadBytesMin || largest != DoorReadBytesMax {
		t.Fatalf("read lengths from %d to %d", smallest, largest)
	}
	if shortest > DoorHoldMin+100*time.Millisecond || longest < DoorHoldMax-100*time.Millisecond {
		t.Fatalf("holds from %v to %v", shortest, longest)
	}
	if DefaultDoorDraws.ReadBytes == nil || DefaultDoorDraws.Hold == nil {
		t.Fatal("the default draws are not set")
	}
}

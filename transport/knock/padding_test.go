package knock

import (
	"bytes"
	"testing"
)

func TestPaddingStaysInItsRange(t *testing.T) {
	seen := map[int]bool{}
	for i := 0; i < 5000; i++ {
		padding := Padding()
		if len(padding) > KnockPaddingBytesMax {
			t.Fatalf("padding of %d bytes", len(padding))
		}
		seen[len(padding)] = true
	}
	if !seen[0] || !seen[KnockPaddingBytesMax] || len(seen) != KnockPaddingBytesMax+1 {
		t.Fatalf("%d padding sizes, 0 %v, %d %v", len(seen), seen[0], KnockPaddingBytesMax, seen[KnockPaddingBytesMax])
	}
}

func TestPaddedPayloadParses(t *testing.T) {
	want := Payload{Protocol: PROTOCOL, Role: KnockRoleClient, IsJoin: true, Time: 1761600000000000000}
	for _, padding := range [][]byte{nil, bytes.Repeat([]byte{'}'}, KnockPaddingBytesMax), {0, 0xff, '{', '"'}} {
		got, err := ParsePayload(append(want.Marshal(), padding...))
		if err != nil || got != want {
			t.Fatalf("padding %x: %+v %v", padding, got, err)
		}
	}
}

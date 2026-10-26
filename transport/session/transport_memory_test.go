package session

import (
	"errors"
	"testing"
)

func TestTransportMemory(t *testing.T) {
	memory := NewTransportMemory(1000)
	spans := memory.Spans()
	first, _ := spans()
	second, _ := spans()
	if err := first.ReserveMemory(600, 255); err != nil {
		t.Fatal(err)
	}
	if err := second.ReserveMemory(500, 255); !errors.Is(err, ErrMemoryExhausted) {
		t.Fatalf("past the cap: %v", err)
	}
	if err := second.ReserveMemory(400, 128); err != nil {
		t.Fatal(err)
	}
	if memory.Used() != 1000 {
		t.Fatalf("used %d", memory.Used())
	}
	first.ReleaseMemory(100)
	first.ReleaseMemory(10000)
	if memory.Used() != 400 {
		t.Fatalf("used %d after releases", memory.Used())
	}
	second.Done()
	if memory.Used() != 0 {
		t.Fatalf("used %d after done", memory.Used())
	}
}

//go:build darwin

package session

import (
	"bytes"
	"fmt"
	"os"
	"syscall"
	"unsafe"
)

// openTerminal opens a new pseudo-terminal pair through /dev/ptmx. It
// returns the system's error, with nothing left open.
func openTerminal() (*os.File, *os.File, error) {
	master, err := os.OpenFile("/dev/ptmx", os.O_RDWR|syscall.O_NOCTTY, 0)
	if err != nil {
		return nil, nil, fmt.Errorf("open /dev/ptmx: %w", err)
	}
	if err := ioctl(master, syscall.TIOCPTYGRANT, nil); err != nil {
		master.Close()
		return nil, nil, fmt.Errorf("grant pseudo-terminal: %w", err)
	}
	if err := ioctl(master, syscall.TIOCPTYUNLK, nil); err != nil {
		master.Close()
		return nil, nil, fmt.Errorf("unlock pseudo-terminal: %w", err)
	}
	var buffer [128]byte
	if err := ioctl(master, syscall.TIOCPTYGNAME, unsafe.Pointer(&buffer[0])); err != nil {
		master.Close()
		return nil, nil, fmt.Errorf("name pseudo-terminal: %w", err)
	}
	end := bytes.IndexByte(buffer[:], 0)
	if end < 0 {
		end = len(buffer)
	}
	name := string(buffer[:end])
	slave, err := os.OpenFile(name, os.O_RDWR|syscall.O_NOCTTY, 0)
	if err != nil {
		master.Close()
		return nil, nil, fmt.Errorf("open %s: %w", name, err)
	}
	return master, slave, nil
}

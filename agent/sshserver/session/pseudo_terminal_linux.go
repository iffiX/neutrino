//go:build linux

package session

import (
	"fmt"
	"os"
	"strconv"
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
	unlock := int32(0)
	if err := ioctl(master, syscall.TIOCSPTLCK, unsafe.Pointer(&unlock)); err != nil {
		master.Close()
		return nil, nil, fmt.Errorf("unlock pseudo-terminal: %w", err)
	}
	var number uint32
	if err := ioctl(master, syscall.TIOCGPTN, unsafe.Pointer(&number)); err != nil {
		master.Close()
		return nil, nil, fmt.Errorf("number pseudo-terminal: %w", err)
	}
	name := "/dev/pts/" + strconv.FormatUint(uint64(number), 10)
	slave, err := os.OpenFile(name, os.O_RDWR|syscall.O_NOCTTY, 0)
	if err != nil {
		master.Close()
		return nil, nil, fmt.Errorf("open %s: %w", name, err)
	}
	return master, slave, nil
}

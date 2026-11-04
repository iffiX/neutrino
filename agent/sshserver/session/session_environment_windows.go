//go:build windows

package session

import (
	"fmt"
	"syscall"
	"unicode/utf16"
	"unsafe"
)

// The userenv functions that build an account's environment from its token.
var (
	userenv                     = syscall.NewLazyDLL("userenv.dll")
	procCreateEnvironmentBlock  = userenv.NewProc("CreateEnvironmentBlock")
	procDestroyEnvironmentBlock = userenv.NewProc("DestroyEnvironmentBlock")
)

// sessionEnvironment returns the environment a shell or a command starts
// from: the account's as the registry holds it now, SHELL naming the
// account's shell; the environment the server started with when the
// registry's cannot be built.
func sessionEnvironment(account Account) []string {
	environment, err := registryEnvironment()
	if err != nil {
		return append([]string{}, account.Environment...)
	}
	return withVariable(environment, "SHELL", account.Shell)
}

// registryEnvironment returns the environment the registry holds now for
// the account the process runs as, built from the process's own token with
// nothing of the process's own. It returns the token's or the call's error.
func registryEnvironment() ([]string, error) {
	process, err := syscall.GetCurrentProcess()
	if err != nil {
		return nil, fmt.Errorf("current process: %w", err)
	}
	var token syscall.Token
	if err := syscall.OpenProcessToken(process, syscall.TOKEN_QUERY|syscall.TOKEN_DUPLICATE, &token); err != nil {
		return nil, fmt.Errorf("open process token: %w", err)
	}
	defer token.Close()
	var block *uint16
	result, _, err := procCreateEnvironmentBlock.Call(uintptr(unsafe.Pointer(&block)), uintptr(token), 0)
	if result == 0 {
		return nil, fmt.Errorf("create environment block: %w", err)
	}
	defer procDestroyEnvironmentBlock.Call(uintptr(unsafe.Pointer(block)))
	return environmentEntries(block), nil
}

// environmentEntries returns the NAME=value entries of an environment
// block, each ended by a NUL and the block by an empty entry.
func environmentEntries(block *uint16) []string {
	entries := []string{}
	for start := unsafe.Pointer(block); ; {
		length := 0
		for *(*uint16)(unsafe.Add(start, 2*length)) != 0 {
			length++
		}
		if length == 0 {
			return entries
		}
		entries = append(entries, string(utf16.Decode(unsafe.Slice((*uint16)(start), length))))
		start = unsafe.Add(start, 2*(length+1))
	}
}

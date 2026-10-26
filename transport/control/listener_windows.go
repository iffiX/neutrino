//go:build windows

package control

import (
	"errors"
	"fmt"
	"net"
	"os"
	"sync"
	"syscall"
	"time"
	"unsafe"
)

// The named pipe constants kernel32 takes.
const (
	pipeAccessDuplex        = 0x00000003
	fileFlagFirstInstance   = 0x00080000
	pipeTypeByte            = 0x00000000
	pipeReadModeByte        = 0x00000000
	pipeWait                = 0x00000000
	pipeRejectRemoteClients = 0x00000008
	pipeUnlimitedInstances  = 255
	pipeBufferBytes         = 64 * 1024
	errorPipeConnected      = syscall.Errno(535)
	errorNoData             = syscall.Errno(232)
	genericRead             = 0x80000000
	genericWrite            = 0x40000000
	openExisting            = 3
	sddlRevision1           = 1
)

// The access lists: the owner, SYSTEM and the administrators for the hub and
// the agent, the owner alone for a client.
const (
	pipeSddlShared  = "D:P(A;;GA;;;OW)(A;;GA;;;SY)(A;;GA;;;BA)"
	pipeSddlPrivate = "D:P(A;;GA;;;OW)"
)

var (
	kernel32                 = syscall.NewLazyDLL("kernel32.dll")
	advapi32                 = syscall.NewLazyDLL("advapi32.dll")
	procCreateNamedPipeW     = kernel32.NewProc("CreateNamedPipeW")
	procConnectNamedPipe     = kernel32.NewProc("ConnectNamedPipe")
	procDisconnectNamedPipe  = kernel32.NewProc("DisconnectNamedPipe")
	procConvertSddl          = advapi32.NewProc("ConvertStringSecurityDescriptorToSecurityDescriptorW")
	procLocalFree            = kernel32.NewProc("LocalFree")
	procWaitNamedPipeW       = kernel32.NewProc("WaitNamedPipeW")
	procSetNamedPipeHandleSt = kernel32.NewProc("SetNamedPipeHandleState")
)

// pipeListener accepts connections on a named pipe, one instance per
// connection, each created when the previous one connected.
type pipeListener struct {
	name     string
	security *syscall.SecurityAttributes
	isFirst  bool

	// mu guards isClosed and pending.
	mu       sync.Mutex
	isClosed bool
	pending  syscall.Handle
}

// pipeAddr is the listener's address.
type pipeAddr string

func (a pipeAddr) Network() string { return "pipe" }
func (a pipeAddr) String() string  { return string(a) }

// pipeConn is one connected pipe instance.
type pipeConn struct {
	file *os.File
	name string
}

func (c *pipeConn) Read(p []byte) (int, error)         { return c.file.Read(p) }
func (c *pipeConn) Write(p []byte) (int, error)        { return c.file.Write(p) }
func (c *pipeConn) LocalAddr() net.Addr                { return pipeAddr(c.name) }
func (c *pipeConn) RemoteAddr() net.Addr               { return pipeAddr(c.name) }
func (c *pipeConn) SetDeadline(t time.Time) error      { return c.file.SetDeadline(t) }
func (c *pipeConn) SetReadDeadline(t time.Time) error  { return c.file.SetReadDeadline(t) }
func (c *pipeConn) SetWriteDeadline(t time.Time) error { return c.file.SetWriteDeadline(t) }

func (c *pipeConn) Close() error {
	handle := syscall.Handle(c.file.Fd())
	_, _, _ = procDisconnectNamedPipe.Call(uintptr(handle))
	return c.file.Close()
}

// listenPipe opens a named pipe listener with the access list isPrivate
// picks.
func listenPipe(path string, isPrivate bool) (net.Listener, error) {
	sddl := pipeSddlShared
	if isPrivate {
		sddl = pipeSddlPrivate
	}
	security, err := securityAttributes(sddl)
	if err != nil {
		return nil, err
	}
	listener := &pipeListener{name: path, security: security, isFirst: true}
	handle, err := listener.createInstance()
	if err != nil {
		return nil, err
	}
	listener.pending = handle
	return listener, nil
}

// createInstance makes one pipe instance, the first one refusing a name
// another program holds.
func (l *pipeListener) createInstance() (syscall.Handle, error) {
	flags := uintptr(pipeAccessDuplex)
	if l.isFirst {
		flags |= fileFlagFirstInstance
		l.isFirst = false
	}
	name, err := syscall.UTF16PtrFromString(l.name)
	if err != nil {
		return 0, err
	}
	handle, _, callErr := procCreateNamedPipeW.Call(
		uintptr(unsafe.Pointer(name)),
		flags,
		uintptr(pipeTypeByte|pipeReadModeByte|pipeWait|pipeRejectRemoteClients),
		uintptr(pipeUnlimitedInstances),
		uintptr(pipeBufferBytes),
		uintptr(pipeBufferBytes),
		0,
		uintptr(unsafe.Pointer(l.security)),
	)
	if syscall.Handle(handle) == syscall.InvalidHandle {
		return 0, fmt.Errorf("create pipe %s: %w", l.name, callErr)
	}
	return syscall.Handle(handle), nil
}

// Accept waits for the next client of the pipe.
func (l *pipeListener) Accept() (net.Conn, error) {
	for {
		l.mu.Lock()
		if l.isClosed {
			l.mu.Unlock()
			return nil, ErrListenerClosed
		}
		handle := l.pending
		l.mu.Unlock()
		result, _, callErr := procConnectNamedPipe.Call(uintptr(handle), 0)
		var errno syscall.Errno
		isConnected := result != 0 || (errors.As(callErr, &errno) && errno == errorPipeConnected)
		l.mu.Lock()
		if l.isClosed {
			l.mu.Unlock()
			syscall.CloseHandle(handle)
			return nil, ErrListenerClosed
		}
		if !isConnected {
			l.mu.Unlock()
			if errors.As(callErr, &errno) && errno == errorNoData {
				_, _, _ = procDisconnectNamedPipe.Call(uintptr(handle))
				continue
			}
			return nil, fmt.Errorf("connect pipe %s: %w", l.name, callErr)
		}
		next, err := l.createInstance()
		if err != nil {
			l.mu.Unlock()
			syscall.CloseHandle(handle)
			return nil, err
		}
		l.pending = next
		l.mu.Unlock()
		return &pipeConn{file: os.NewFile(uintptr(handle), l.name), name: l.name}, nil
	}
}

// Close ends the listener: it connects to its own pending instance so a
// waiting Accept returns.
func (l *pipeListener) Close() error {
	l.mu.Lock()
	if l.isClosed {
		l.mu.Unlock()
		return nil
	}
	l.isClosed = true
	pending := l.pending
	l.mu.Unlock()
	name, err := syscall.UTF16PtrFromString(l.name)
	if err == nil {
		handle, err := syscall.CreateFile(name, genericRead|genericWrite, 0, nil, openExisting, 0, 0)
		if err == nil {
			syscall.CloseHandle(handle)
		}
	}
	time.AfterFunc(time.Second, func() { syscall.CloseHandle(pending) })
	return nil
}

// Addr is the pipe's name.
func (l *pipeListener) Addr() net.Addr {
	return pipeAddr(l.name)
}

// securityAttributes turns an SDDL string into the attributes a pipe is
// created with.
func securityAttributes(sddl string) (*syscall.SecurityAttributes, error) {
	text, err := syscall.UTF16PtrFromString(sddl)
	if err != nil {
		return nil, err
	}
	var descriptor uintptr
	result, _, callErr := procConvertSddl.Call(
		uintptr(unsafe.Pointer(text)),
		uintptr(sddlRevision1),
		uintptr(unsafe.Pointer(&descriptor)),
		0,
	)
	if result == 0 {
		return nil, fmt.Errorf("security descriptor: %w", callErr)
	}
	attributes := &syscall.SecurityAttributes{
		Length:             uint32(unsafe.Sizeof(syscall.SecurityAttributes{})),
		SecurityDescriptor: descriptor,
		InheritHandle:      0,
	}
	return attributes, nil
}

// DialPipe connects to a named pipe, for the tests and the probe of a pipe.
func DialPipe(path string) (net.Conn, error) {
	name, err := syscall.UTF16PtrFromString(path)
	if err != nil {
		return nil, err
	}
	handle, err := syscall.CreateFile(name, genericRead|genericWrite, 0, nil, openExisting, 0, 0)
	if err != nil {
		return nil, fmt.Errorf("open pipe %s: %w", path, err)
	}
	return &pipeConn{file: os.NewFile(uintptr(handle), path), name: path}, nil
}

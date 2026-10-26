//go:build windows

package session

import (
	"errors"
	"fmt"
	"os"
	"os/exec"
	"runtime"
	"strings"
	"sync"
	"syscall"
	"time"
	"unicode/utf16"
	"unsafe"

	"golang.org/x/crypto/ssh"
)

// The kernel32 functions of the pseudo console and of the attribute list
// that hands it to a process.
var (
	kernel32                              = syscall.NewLazyDLL("kernel32.dll")
	procCreatePseudoConsole               = kernel32.NewProc("CreatePseudoConsole")
	procResizePseudoConsole               = kernel32.NewProc("ResizePseudoConsole")
	procClosePseudoConsole                = kernel32.NewProc("ClosePseudoConsole")
	procInitializeProcThreadAttributeList = kernel32.NewProc("InitializeProcThreadAttributeList")
	procUpdateProcThreadAttribute         = kernel32.NewProc("UpdateProcThreadAttribute")
	procDeleteProcThreadAttributeList     = kernel32.NewProc("DeleteProcThreadAttributeList")
)

// startupInfoEx is STARTUPINFOEXW.
type startupInfoEx struct {
	startupInfo   syscall.StartupInfo
	attributeList *byte
}

// terminalProcess is a shell or a command on a pseudo console (ConPTY).
type terminalProcess struct {
	process syscall.Handle
	input   *os.File
	output  *os.File
	// outputDone is closed once the console's output reached its end.
	outputDone chan struct{}
	// mutex guards console and isClosed.
	mutex    sync.Mutex
	console  uintptr
	isClosed bool
}

// startTerminalProcess starts cmd's command line on a new pseudo console
// of the requested size: the channel's data to the console's input and the
// console's output to the channel's data. It returns the console's or the
// start's error, with nothing left running.
func startTerminalProcess(cmd *exec.Cmd, channel ssh.Channel, terminal terminalRequest) (*terminalProcess, error) {
	var inputRead, inputWrite, outputRead, outputWrite syscall.Handle
	if err := syscall.CreatePipe(&inputRead, &inputWrite, nil, 0); err != nil {
		return nil, fmt.Errorf("make console input pipe: %w", err)
	}
	if err := syscall.CreatePipe(&outputRead, &outputWrite, nil, 0); err != nil {
		closeHandles(inputRead, inputWrite)
		return nil, fmt.Errorf("make console output pipe: %w", err)
	}
	var console uintptr
	result, _, _ := procCreatePseudoConsole.Call(
		consoleSize(terminal.columns, terminal.rows),
		uintptr(inputRead),
		uintptr(outputWrite),
		0,
		uintptr(unsafe.Pointer(&console)),
	)
	closeHandles(inputRead, outputWrite)
	if result != 0 {
		closeHandles(inputWrite, outputRead)
		return nil, fmt.Errorf("create pseudo console: HRESULT 0x%08X", uint32(result))
	}
	process, err := createConsoleProcess(console, cmd)
	if err != nil {
		procClosePseudoConsole.Call(console)
		closeHandles(inputWrite, outputRead)
		return nil, err
	}
	started := &terminalProcess{
		process:    process,
		input:      os.NewFile(uintptr(inputWrite), "console-input"),
		output:     os.NewFile(uintptr(outputRead), "console-output"),
		outputDone: make(chan struct{}),
		console:    console,
	}
	go func() {
		defer close(started.outputDone)
		copyStream(channel, started.output)
	}()
	go copyStream(started.input, channel)
	return started, nil
}

// wait returns once the process ended and the console, closed after
// SessionTerminalDrain, passed its last output on.
func (p *terminalProcess) wait() exitStatus {
	syscall.WaitForSingleObject(p.process, syscall.INFINITE)
	var code uint32
	if err := syscall.GetExitCodeProcess(p.process, &code); err != nil {
		code = SessionExitUnstartable
	}
	syscall.CloseHandle(p.process)
	time.Sleep(SessionTerminalDrain)
	p.closeConsole()
	timer := time.NewTimer(SessionConsoleDrain)
	select {
	case <-p.outputDone:
	case <-timer.C:
	}
	timer.Stop()
	closeFiles(p.input, p.output)
	return exitStatus{code: code}
}

// resize sets the console's size; a closed console is left as it is.
func (p *terminalProcess) resize(columns, rows uint32) {
	p.mutex.Lock()
	defer p.mutex.Unlock()
	if !p.isClosed {
		procResizePseudoConsole.Call(p.console, consoleSize(columns, rows))
	}
}

// abandon closes the console once the channel is gone, which ends the
// processes attached to it.
func (p *terminalProcess) abandon() {
	p.closeConsole()
	p.input.Close()
}

// closeConsole closes the pseudo console once.
func (p *terminalProcess) closeConsole() {
	p.mutex.Lock()
	defer p.mutex.Unlock()
	if p.isClosed {
		return
	}
	p.isClosed = true
	procClosePseudoConsole.Call(p.console)
}

// createConsoleProcess starts cmd's command line attached to console, in
// cmd's directory with cmd's environment. It returns the process handle, or
// the system's error.
func createConsoleProcess(console uintptr, cmd *exec.Cmd) (syscall.Handle, error) {
	var size uintptr
	procInitializeProcThreadAttributeList.Call(0, 1, 0, uintptr(unsafe.Pointer(&size)))
	if size == 0 {
		return 0, errors.New("size the process attribute list")
	}
	list := make([]byte, size)
	ok, _, err := procInitializeProcThreadAttributeList.Call(uintptr(unsafe.Pointer(&list[0])), 1, 0, uintptr(unsafe.Pointer(&size)))
	if ok == 0 {
		return 0, fmt.Errorf("make the process attribute list: %w", err)
	}
	defer procDeleteProcThreadAttributeList.Call(uintptr(unsafe.Pointer(&list[0])))
	ok, _, err = procUpdateProcThreadAttribute.Call(
		uintptr(unsafe.Pointer(&list[0])),
		0,
		SessionAttributePseudoConsole,
		console,
		unsafe.Sizeof(console),
		0,
		0,
	)
	if ok == 0 {
		return 0, fmt.Errorf("attach the pseudo console: %w", err)
	}
	commandLine, err := syscall.UTF16PtrFromString(cmd.SysProcAttr.CmdLine)
	if err != nil {
		return 0, fmt.Errorf("command line: %w", err)
	}
	var directory *uint16
	if cmd.Dir != "" {
		if directory, err = syscall.UTF16PtrFromString(cmd.Dir); err != nil {
			return 0, fmt.Errorf("directory: %w", err)
		}
	}
	environment, err := environmentBlock(cmd.Env)
	if err != nil {
		return 0, err
	}
	info := startupInfoEx{attributeList: &list[0]}
	info.startupInfo.Cb = uint32(unsafe.Sizeof(info))
	info.startupInfo.Flags = syscall.STARTF_USESTDHANDLES
	var processInfo syscall.ProcessInformation
	err = syscall.CreateProcess(
		nil,
		commandLine,
		nil,
		nil,
		false,
		SessionCreateExtendedStartupInfo|SessionCreateUnicodeEnvironment,
		environment,
		directory,
		&info.startupInfo,
		&processInfo,
	)
	runtime.KeepAlive(list)
	if err != nil {
		return 0, fmt.Errorf("start %s: %w", cmd.Path, err)
	}
	syscall.CloseHandle(processInfo.Thread)
	return processInfo.Process, nil
}

// environmentBlock returns NAME=value entries as the block CreateProcess
// takes. It returns an error for an entry holding a NUL.
func environmentBlock(environment []string) (*uint16, error) {
	block := []uint16{}
	for _, entry := range environment {
		if strings.ContainsRune(entry, 0) {
			return nil, fmt.Errorf("environment entry %q holds a NUL", entry)
		}
		block = append(block, utf16.Encode([]rune(entry))...)
		block = append(block, 0)
	}
	if len(environment) == 0 {
		block = append(block, 0)
	}
	block = append(block, 0)
	return &block[0], nil
}

// consoleSize returns a size as the COORD a pseudo console takes, each side
// bounded to what a SHORT holds.
func consoleSize(columns, rows uint32) uintptr {
	width := uint32(boundedConsoleCells(columns, SessionDefaultColumns))
	height := uint32(boundedConsoleCells(rows, SessionDefaultRows))
	return uintptr(width | height<<16)
}

// boundedConsoleCells returns a size in cells that a SHORT holds, fallback
// for 0.
func boundedConsoleCells(value uint32, fallback uint16) uint16 {
	if value == 0 {
		return fallback
	}
	if value > 0x7FFF {
		return 0x7FFF
	}
	return uint16(value)
}

// closeHandles closes each handle, ignoring an error.
func closeHandles(handles ...syscall.Handle) {
	for _, handle := range handles {
		syscall.CloseHandle(handle)
	}
}

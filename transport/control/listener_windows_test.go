//go:build windows

package control

import (
	"bufio"
	"errors"
	"fmt"
	"net"
	"os"
	"testing"
	"time"
)

// testPipeName is a pipe name no other process holds.
func testPipeName(t *testing.T) string {
	t.Helper()
	return fmt.Sprintf(`%sneutrino_test_%d_%d`, ControlPipePrefix, os.Getpid(), time.Now().UnixNano())
}

// acceptOne accepts one connection in the background; a listener closed
// under it closes the channel with no connection.
func acceptOne(t *testing.T, listener net.Listener) <-chan net.Conn {
	t.Helper()
	accepted := make(chan net.Conn, 1)
	go func() {
		conn, err := listener.Accept()
		if err != nil {
			if !errors.Is(err, ErrListenerClosed) {
				t.Error(err)
			}
			close(accepted)
			return
		}
		accepted <- conn
	}()
	return accepted
}

func TestPipeWritesWhileAReadWaits(t *testing.T) {
	listener, err := Listen(testPipeName(t), false)
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	accepted := acceptOne(t, listener)
	client, err := DialPipe(listener.Addr().String())
	if err != nil {
		t.Fatal(err)
	}
	defer client.Close()
	server := <-accepted
	if server == nil {
		t.Fatal("no connection accepted")
	}
	defer server.Close()

	// The server waits for the client's next line, as the transport waits
	// for the Python's; a write from another goroutine must not wait on it.
	serverRead := make(chan string, 1)
	go func() {
		line, err := bufio.NewReader(server).ReadString('\n')
		if err != nil {
			serverRead <- "error: " + err.Error()
			return
		}
		serverRead <- line
	}()
	time.Sleep(100 * time.Millisecond)
	written := make(chan error, 1)
	go func() {
		_, err := server.Write([]byte("event\n"))
		written <- err
	}()
	select {
	case err := <-written:
		if err != nil {
			t.Fatal(err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("the write waited behind the read")
	}
	_ = client.SetReadDeadline(time.Now().Add(5 * time.Second))
	line, err := bufio.NewReader(client).ReadString('\n')
	if err != nil || line != "event\n" {
		t.Fatalf("client read %q %v", line, err)
	}
	if _, err := client.Write([]byte("answer\n")); err != nil {
		t.Fatal(err)
	}
	select {
	case line := <-serverRead:
		if line != "answer\n" {
			t.Fatalf("server read %q", line)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("the server's read did not return")
	}
}

func TestPipeAcceptsSeveralAndCloses(t *testing.T) {
	listener, err := Listen(testPipeName(t), true)
	if err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 3; i++ {
		accepted := acceptOne(t, listener)
		client, err := DialPipe(listener.Addr().String())
		if err != nil {
			t.Fatal(err)
		}
		server := <-accepted
		if server == nil {
			t.Fatal("no connection accepted")
		}
		if _, err := client.Write([]byte("x")); err != nil {
			t.Fatal(err)
		}
		buffer := make([]byte, 1)
		_ = server.SetReadDeadline(time.Now().Add(5 * time.Second))
		if _, err := server.Read(buffer); err != nil || buffer[0] != 'x' {
			t.Fatalf("read %q %v", buffer, err)
		}
		client.Close()
		server.Close()
	}
	pending := acceptOne(t, listener)
	if err := listener.Close(); err != nil {
		t.Fatal(err)
	}
	select {
	case conn := <-pending:
		if conn != nil {
			t.Fatal("a connection came after the close")
		}
	case <-time.After(5 * time.Second):
		t.Fatal("Accept did not return after Close")
	}
	if _, err := DialPipe(listener.Addr().String()); err == nil {
		t.Fatal("the pipe still answers after the close")
	}
}

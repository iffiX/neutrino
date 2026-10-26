package control

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"net"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/iffiX/neutrino/transport/handshake"
	"github.com/iffiX/neutrino/transport/relay"
	"github.com/iffiX/neutrino/transport/session"
)

const testSecret = "0000000000000000000000000000000000000000000000000000000000000042"

// hubUnderTest is a hub's local channel with a relay that listens nowhere.
type hubUnderTest struct {
	control *HubControl
	hub     *relay.Hub
	socket  string
}

func newHubUnderTest(t *testing.T) *hubUnderTest {
	t.Helper()
	dir, err := os.MkdirTemp("", "nc")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.RemoveAll(dir) })
	socket := filepath.Join(dir, "hub.sock")
	listener, err := Listen(socket, false)
	if err != nil {
		t.Fatal(err)
	}
	info, err := os.Stat(socket)
	if err != nil || info.Mode().Perm() != ControlSocketMode {
		t.Fatalf("socket mode %v %v", info, err)
	}
	hubControl := NewHubControl(listener, testSecret, filepath.Join(dir, "keys"), nil)
	key, _ := handshake.GenerateKey()
	hub, err := relay.NewHub(relay.HubConfig{Key: key}, hubControl)
	if err != nil {
		t.Fatal(err)
	}
	hubControl.SetHub(hub)
	go hubControl.Serve()
	t.Cleanup(func() {
		hub.Close()
		hubControl.Close()
	})
	return &hubUnderTest{control: hubControl, hub: hub, socket: socket}
}

// localConn is a test's connection to the local channel.
type localConn struct {
	conn   net.Conn
	reader *bufio.Reader
}

func (h *hubUnderTest) connect(t *testing.T, first string) *localConn {
	t.Helper()
	conn, err := net.DialTimeout("unix", h.socket, time.Second)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { conn.Close() })
	_, _ = conn.Write([]byte(first + "\n"))
	return &localConn{conn: conn, reader: bufio.NewReader(conn)}
}

// connectControl opens the control connection and waits until the hub holds it.
func (h *hubUnderTest) connectControl(t *testing.T) *localConn {
	t.Helper()
	conn := h.connect(t, `{"secret":"`+testSecret+`","op":"control"}`)
	deadline := time.Now().Add(5 * time.Second)
	for !h.control.IsConnected() && time.Now().Before(deadline) {
		time.Sleep(5 * time.Millisecond)
	}
	if !h.control.IsConnected() {
		t.Fatal("the control connection was not taken")
	}
	return conn
}

func (c *localConn) write(t *testing.T, object map[string]any) {
	t.Helper()
	line, _ := json.Marshal(object)
	_, _ = c.conn.Write(append(line, '\n'))
}

func (c *localConn) read(t *testing.T) map[string]any {
	t.Helper()
	_ = c.conn.SetReadDeadline(time.Now().Add(5 * time.Second))
	line, err := c.reader.ReadBytes('\n')
	if err != nil {
		t.Fatalf("read line: %v", err)
	}
	var object map[string]any
	if err := json.Unmarshal(line, &object); err != nil {
		t.Fatal(err)
	}
	return object
}

func (c *localConn) isClosed(t *testing.T) bool {
	t.Helper()
	_ = c.conn.SetReadDeadline(time.Now().Add(3 * time.Second))
	_, err := c.reader.ReadByte()
	return err != nil && !errors.Is(err, os.ErrDeadlineExceeded)
}

func TestSecretOnEveryConnection(t *testing.T) {
	hub := newHubUnderTest(t)
	cases := []struct {
		name  string
		first string
	}{
		{"a wrong secret", `{"secret":"0000000000000000000000000000000000000000000000000000000000000000","op":"control"}`},
		{"no secret", `{"op":"control"}`},
		{"an unknown op", `{"secret":"` + testSecret + `","op":"listen"}`},
		{"not json", `hello`},
		{"an attach of no stream", `{"secret":"` + testSecret + `","op":"attach","stream":"t9"}`},
		{"an open on no session", `{"secret":"` + testSecret + `","op":"open","session":"s9","open":{"kind":"file"}}`},
	}
	for _, c := range cases {
		t.Run(c.name, func(t *testing.T) {
			conn := hub.connect(t, c.first)
			if !conn.isClosed(t) {
				t.Fatal("the connection stayed open")
			}
		})
	}
	t.Run("a late first line", func(t *testing.T) {
		conn, err := net.DialTimeout("unix", hub.socket, time.Second)
		if err != nil {
			t.Fatal(err)
		}
		defer conn.Close()
		_ = conn.SetReadDeadline(time.Now().Add(ControlSecretTimeout + 2*time.Second))
		if _, err := conn.Read(make([]byte, 1)); err == nil || errors.Is(err, os.ErrDeadlineExceeded) {
			t.Fatalf("a silent connection was kept: %v", err)
		}
	})
	if hub.control.IsConnected() {
		t.Fatal("a refused connection counts as the control connection")
	}
}

func TestCommandsAndQuestions(t *testing.T) {
	hub := newHubUnderTest(t)
	control := hub.connectControl(t)
	control.write(t, map[string]any{"id": "1", "command": "keys_reload"})
	if answer := control.read(t); answer["id"] != "1" || answer["code"] != nil {
		t.Fatalf("keys_reload %v", answer)
	}
	control.write(t, map[string]any{"id": "2", "command": "session_close", "session": "s9", "code": "replaced", "params": map[string]any{}})
	if answer := control.read(t); answer["id"] != "2" || answer["code"] != CodeSessionUnknown {
		t.Fatalf("session_close %v", answer)
	}
	control.write(t, map[string]any{"id": "3", "command": "streams_close", "binding_id": "b", "kind": "web", "code": "permission_denied", "params": map[string]any{"kind": "web"}})
	if answer := control.read(t); answer["id"] != "3" || answer["code"] != nil {
		t.Fatalf("streams_close %v", answer)
	}
	control.write(t, map[string]any{"id": "4", "command": "dance"})
	if answer := control.read(t); answer["code"] != CodeCommandUnknown {
		t.Fatalf("unknown command %v", answer)
	}

	answers := make(chan map[string]any, 1)
	go func() {
		answer, err := hub.control.Ask(context.Background(), QuestionPeer, map[string]any{"public_key": "k"})
		if err != nil {
			answers <- map[string]any{"error": err.Error()}
			return
		}
		answers <- answer
	}()
	question := control.read(t)
	if question["question"] != QuestionPeer || question["public_key"] != "k" {
		t.Fatalf("question %v", question)
	}
	control.write(t, map[string]any{"id": question["id"], "binding_id": "b1", "role": "agent", "psk": "p"})
	if answer := <-answers; answer["binding_id"] != "b1" {
		t.Fatalf("answer %v", answer)
	}

	go func() {
		_, err := hub.control.Ask(context.Background(), QuestionTicket, map[string]any{"ticket": "t"})
		var refusal *session.Refusal
		if errors.As(err, &refusal) {
			answers <- map[string]any{"code": refusal.Code, "params": refusal.Params}
			return
		}
		answers <- map[string]any{"error": err.Error()}
	}()
	question = control.read(t)
	control.write(t, map[string]any{"id": question["id"], "code": "ticket_spent", "params": map[string]any{}})
	if answer := <-answers; answer["code"] != "ticket_spent" {
		t.Fatalf("refusal %v", answer)
	}

	ctx, cancel := context.WithTimeout(context.Background(), 200*time.Millisecond)
	defer cancel()
	started := time.Now()
	_, err := hub.control.Ask(ctx, QuestionEntry, map[string]any{})
	if !errors.Is(err, relay.ErrControlUnavailable) || time.Since(started) < 200*time.Millisecond {
		t.Fatalf("unanswered question: %v after %v", err, time.Since(started))
	}
	control.read(t)

	replacement := hub.connectControl(t)
	if !control.isClosed(t) {
		t.Fatal("the first control connection survived the second")
	}
	replacement.write(t, map[string]any{"id": "5", "command": "keys_reload"})
	if answer := replacement.read(t); answer["id"] != "5" {
		t.Fatalf("on the replacement %v", answer)
	}
	hub.control.Close()
	if _, err := hub.control.Ask(context.Background(), QuestionToken, nil); !errors.Is(err, relay.ErrControlUnavailable) {
		t.Fatalf("after close: %v", err)
	}
}

func TestFrameLinesKeepTheFrame(t *testing.T) {
	hub := newHubUnderTest(t)
	control := hub.connectControl(t)
	frame := []byte(`{"type":"hello","id":"b1","protocol":4}`)
	hub.control.Frame("s1", frame)
	line := control.read(t)
	inner, _ := json.Marshal(line["frame"])
	var want, got map[string]any
	_ = json.Unmarshal(frame, &want)
	_ = json.Unmarshal(inner, &got)
	if line["session"] != "s1" || got["type"] != want["type"] || got["id"] != want["id"] {
		t.Fatalf("frame line %v", line)
	}
	hub.control.Event(EventSessionEnd, map[string]any{"session": "s1", "reason": "x"})
	if event := control.read(t); event["event"] != EventSessionEnd || event["session"] != "s1" {
		t.Fatalf("event %v", event)
	}
	control.write(t, map[string]any{"frame": map[string]any{"type": "welcome"}, "session": "s9"})
	control.write(t, map[string]any{"id": "9", "command": "keys_reload"})
	if answer := control.read(t); answer["id"] != "9" {
		t.Fatalf("a frame for an unknown session broke the connection: %v", answer)
	}
}

func TestLineLimits(t *testing.T) {
	near, far := net.Pipe()
	defer near.Close()
	defer far.Close()
	conn := NewLineConnection(far)
	go func() {
		_, _ = near.Write(append(make([]byte, ControlLineLimit+1), '\n'))
	}()
	if _, err := conn.ReadLine(); !errors.Is(err, ErrLineTooLong) {
		t.Fatalf("long line: %v", err)
	}
}

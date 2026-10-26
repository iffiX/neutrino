package tests

import (
	"bufio"
	"encoding/json"
	"net"
	"path/filepath"
	"testing"
	"time"

	"github.com/iffiX/neutrino/transport/session"
)

// rawLine opens one connection to a transport's listener and writes its
// first line, the way the Python side opens or attaches a stream.
func rawLine(t *testing.T, path string, first map[string]any) net.Conn {
	t.Helper()
	conn, err := net.DialTimeout("unix", path, 5*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	line, err := json.Marshal(first)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := conn.Write(append(line, '\n')); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { conn.Close() })
	return conn
}

// TestACloseRecordFollowsALargeBody sends a body the
// size of a module package down a stream the hub opened, then the close,
// and expects the agent's side to read every byte and then the close.
func TestACloseRecordFollowsALargeBody(t *testing.T) {
	dir := shortTempDir(t)
	hub := startHub(t, dir, freePort(t), 0)
	hub.records.mu.Lock()
	hub.records.tickets["ticket-agent"] = "dev-9"
	hub.records.mu.Unlock()
	agent := startAgent(t, dir, 0)
	binding, psk := agent.join(t, hub, "ticket-agent", "dev-9")
	agent.dial(t, hub, binding, psk)
	agent.hello(t, hub, binding)
	hub.records.mu.Lock()
	sessionID := hub.records.sessions["dev-9"]
	hub.records.mu.Unlock()

	hubConn := rawLine(t, filepath.Join(dir, "hub.sock"), map[string]any{
		"secret": hubSecret, "op": "open", "session": sessionID,
		"open": map[string]any{"kind": "package", "module": "gitea"},
	})
	event := agent.python.waitEvent("stream")
	agentConn := rawLine(t, filepath.Join(dir, "agent.sock"), map[string]any{
		"secret": agentSecret, "op": "attach", "stream": event["stream"],
	})
	if _, err := agentConn.Write(session.AcceptRecord()); err != nil {
		t.Fatal(err)
	}
	hubReader := bufio.NewReaderSize(hubConn, 1<<20)
	if answer, err := session.ReadRecord(hubReader); err != nil || answer.Type != session.RecordAccept {
		t.Fatalf("the hub's side read %v %v for the accept", answer, err)
	}

	const records = 1923
	chunk := make([]byte, session.RecordBytesMax)
	go func() {
		for i := 0; i < records; i++ {
			if _, err := hubConn.Write(session.EncodeRecord(session.RecordData, chunk)); err != nil {
				return
			}
		}
		_, _ = hubConn.Write(session.CloseRecord("", map[string]any{"sha256": "x"}))
		hubConn.Close()
	}()

	reader := bufio.NewReaderSize(agentConn, 1<<20)
	_ = agentConn.SetReadDeadline(time.Now().Add(60 * time.Second))
	var last session.Record
	total := 0
	count := 0
	for {
		record, err := session.ReadRecord(reader)
		if err != nil {
			break
		}
		last = record
		count++
		if record.Type == session.RecordData {
			total += len(record.Payload)
		}
	}
	if total != records*session.RecordBytesMax {
		t.Fatalf("the agent's side read %d bytes of %d", total, records*session.RecordBytesMax)
	}
	if last.Type != session.RecordClose {
		t.Fatalf("the last record after %d records was type %d, not the close", count, last.Type)
	}
}

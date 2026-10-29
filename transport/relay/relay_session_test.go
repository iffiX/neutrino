package relay

import (
	"context"
	"encoding/binary"
	"encoding/json"
	"errors"
	"io"
	"net"
	"testing"
	"time"

	"github.com/libp2p/go-yamux/v4"

	"github.com/iffiX/neutrino/transport/knock"
	"github.com/iffiX/neutrino/transport/session"
)

// serveAgentStreams answers the streams the hub opens on an agent's session:
// a connect to a port is accepted and echoed, any other port refused
// port_not_published, and a shell is accepted and echoed as records.
func serveAgentStreams(t *testing.T, c *connected, publishedPort int) {
	t.Helper()
	go func() {
		for {
			stream, err := c.session.AcceptStream()
			if err != nil {
				return
			}
			go func(stream *yamux.Stream) {
				record := NewRecordStream(stream)
				open, err := session.ReadRecord(record.Reader)
				if err != nil {
					return
				}
				var body struct {
					Kind string `json:"kind"`
					Port int    `json:"port"`
				}
				_ = json.Unmarshal(open.Payload, &body)
				switch body.Kind {
				case session.KindConnect:
					if body.Port != publishedPort {
						_, _ = stream.Write(session.CloseRecord("port_not_published", map[string]any{"port": body.Port}))
						stream.Close()
						return
					}
					_, _ = stream.Write(session.AcceptRecord())
					_, _ = io.Copy(stream, record.Reader)
					stream.Close()
				case session.KindShell:
					_, _ = stream.Write(session.AcceptRecord())
					for {
						rec, err := session.ReadRecord(record.Reader)
						if err != nil {
							return
						}
						if rec.Type == session.RecordClose {
							return
						}
						_, _ = stream.Write(session.EncodeRecord(rec.Type, append([]byte("echo:"), rec.Payload...)))
					}
				}
			}(stream)
		}
	}()
}

func openStream(t *testing.T, c *connected, kind string, args map[string]any) (*RecordStream, *session.Refusal) {
	t.Helper()
	stream, err := c.session.OpenStream(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	payload := session.OpenRecord(kind, args)[session.RecordHeaderBytes:]
	record, refusal, err := OpenOn(stream, json.RawMessage(payload))
	if err != nil {
		t.Fatal(err)
	}
	return record, refusal
}

func echoServer(t *testing.T) int {
	t.Helper()
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { listener.Close() })
	go func() {
		for {
			conn, err := listener.Accept()
			if err != nil {
				return
			}
			go func() {
				_, _ = io.Copy(conn, conn)
				conn.Close()
			}()
		}
	}()
	return listener.Addr().(*net.TCPAddr).Port
}

func TestConnectRelayedToAnAgent(t *testing.T) {
	hub := newTestHub(t)
	address := hub.listen(t)
	agent := newPeer(t, hub, "dev", "agent")
	agentConn, agentSession := agent.admit(t, hub, address, "dev")
	serveAgentStreams(t, agentConn, 445)
	client := newPeer(t, hub, "cli", "client")
	clientConn, _ := client.admit(t, hub, address, "cli")
	hub.python.mu.Lock()
	hub.python.entries["connect:files"] = entryAnswer{answer: map[string]any{
		"kind": "file", "device_id": "dev",
		"target": map[string]any{"session": agentSession, "open": map[string]any{"kind": "connect", "port": 445, "protocol": "tcp"}},
	}}
	hub.python.entries["connect:closed"] = entryAnswer{answer: map[string]any{
		"kind": "port", "device_id": "dev",
		"target": map[string]any{"session": agentSession, "open": map[string]any{"kind": "connect", "port": 9, "protocol": "tcp"}},
	}}
	hub.python.mu.Unlock()

	record, refusal := openStream(t, clientConn, session.KindConnect, map[string]any{"id": "files"})
	if refusal != nil {
		t.Fatalf("refused %v", refusal)
	}
	payload := make([]byte, 300*1024)
	for i := range payload {
		payload[i] = byte(i)
	}
	go func() { _, _ = record.Stream.Write(payload) }()
	got := make([]byte, len(payload))
	if _, err := io.ReadFull(record.Reader, got); err != nil {
		t.Fatal(err)
	}
	if string(got) != string(payload) {
		t.Fatal("the echoed bytes differ")
	}
	record.Stream.Close()

	_, refusal = openStream(t, clientConn, session.KindConnect, map[string]any{"id": "closed"})
	if refusal == nil || refusal.Code != "port_not_published" {
		t.Fatalf("agent's refusal %v", refusal)
	}
	_, refusal = openStream(t, clientConn, session.KindConnect, map[string]any{"id": "nothing"})
	if refusal == nil || refusal.Code != "service_unknown" {
		t.Fatalf("python's refusal %v", refusal)
	}
}

func TestFarStreamPastTheMemoryCapIsReset(t *testing.T) {
	limit := int64(3*session.StreamWindowInitialBytes + session.StreamWindowInitialBytes/2)
	memory := session.NewTransportMemory(limit)
	hub := newTestHubWith(t, fixedDraws(knock.DoorReadBytesMax, testHold), memory)
	address := hub.listen(t)
	agent := newPeer(t, hub, "dev", "agent")
	agentConn, agentSession := agent.admit(t, hub, address, "dev")
	serveAgentStreams(t, agentConn, 445)
	client := newPeer(t, hub, "cli", "client")
	clientConn, clientSession := client.admit(t, hub, address, "cli")
	hub.python.mu.Lock()
	hub.python.entries["connect:files"] = entryAnswer{answer: map[string]any{
		"kind": "file", "device_id": "dev",
		"target": map[string]any{"session": agentSession, "open": map[string]any{"kind": "connect", "port": 445, "protocol": "tcp"}},
	}}
	hub.python.mu.Unlock()

	stream, err := clientConn.session.OpenStream(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	_ = stream.SetReadDeadline(time.Now().Add(5 * time.Second))
	payload := session.OpenRecord(session.KindConnect, map[string]any{"id": "files"})[session.RecordHeaderBytes:]
	if _, refusal, err := OpenOn(stream, json.RawMessage(payload)); !errors.Is(err, yamux.ErrStreamReset) {
		t.Fatalf("a connect whose far stream is past the cap: %v %v", refusal, err)
	}

	_, refusal := openStream(t, clientConn, session.KindConnect, map[string]any{"id": "nothing"})
	if refusal == nil || refusal.Code != "service_unknown" {
		t.Fatalf("the client's next stream: %v", refusal)
	}
	for _, id := range []string{agentSession, clientSession} {
		if _, err := hub.hub.Session(id); err != nil {
			t.Fatalf("session %s after the refusal: %v", id, err)
		}
	}
	if agentConn.session.IsClosed() || clientConn.session.IsClosed() {
		t.Fatal("a refusal at the cap ended a peer's session")
	}
	deadline := time.Now().Add(3 * time.Second)
	for memory.Used() > 2*session.StreamWindowInitialBytes {
		if time.Now().After(deadline) {
			t.Fatalf("%d bytes held after the refusal", memory.Used())
		}
		time.Sleep(10 * time.Millisecond)
	}
}

func TestConnectDialledByTheHubAndTheLimit(t *testing.T) {
	hub := newTestHub(t)
	address := hub.listen(t)
	client := newPeer(t, hub, "cli", "client")
	clientConn, clientSession := client.admit(t, hub, address, "cli")
	port := echoServer(t)
	hub.python.mu.Lock()
	hub.python.entries["connect:declared"] = entryAnswer{answer: map[string]any{
		"kind": "web", "device_id": "",
		"target": map[string]any{"address": "127.0.0.1", "port": port, "protocol": "tcp"},
	}}
	hub.python.entries["connect:dead"] = entryAnswer{answer: map[string]any{
		"kind": "web", "device_id": "",
		"target": map[string]any{"address": "127.0.0.1", "port": 1, "protocol": "tcp"},
	}}
	hub.python.mu.Unlock()

	record, refusal := openStream(t, clientConn, session.KindConnect, map[string]any{"id": "declared"})
	if refusal != nil {
		t.Fatalf("refused %v", refusal)
	}
	_, _ = record.Stream.Write([]byte("ping"))
	buffer := make([]byte, 4)
	if _, err := io.ReadFull(record.Reader, buffer); err != nil || string(buffer) != "ping" {
		t.Fatalf("echo %q %v", buffer, err)
	}
	_, refusal = openStream(t, clientConn, session.KindConnect, map[string]any{"id": "dead"})
	if refusal == nil || refusal.Code != session.CodeConnectFailed || refusal.Params["reason"] != session.ReasonRefused {
		t.Fatalf("dead port: %v", refusal)
	}

	var open []*RecordStream
	for i := 1; i < session.ConnectStreamsMax; i++ {
		stream, refusal := openStream(t, clientConn, session.KindConnect, map[string]any{"id": "declared"})
		if refusal != nil {
			t.Fatalf("stream %d refused %v", i, refusal)
		}
		open = append(open, stream)
	}
	rs, _ := hub.hub.Session(clientSession)
	if rs.ConnectCount() != session.ConnectStreamsMax {
		t.Fatalf("%d connect streams counted", rs.ConnectCount())
	}
	_, refusal = openStream(t, clientConn, session.KindConnect, map[string]any{"id": "declared"})
	if refusal == nil || refusal.Code != session.CodeConnectLimit || refusal.Params["limit"] != float64(session.ConnectStreamsMax) {
		t.Fatalf("past the limit: %v", refusal)
	}
	for _, stream := range open {
		stream.Stream.Close()
	}
	record.Stream.Close()
	deadline := time.Now().Add(5 * time.Second)
	for rs.ConnectCount() != 0 && time.Now().Before(deadline) {
		time.Sleep(10 * time.Millisecond)
	}
	if rs.ConnectCount() != 0 {
		t.Fatalf("%d connect streams still counted", rs.ConnectCount())
	}
}

func TestStreamsCloseAndAgentOffline(t *testing.T) {
	hub := newTestHub(t)
	address := hub.listen(t)
	agent := newPeer(t, hub, "dev", "agent")
	agentConn, agentSession := agent.admit(t, hub, address, "dev")
	serveAgentStreams(t, agentConn, 445)
	client := newPeer(t, hub, "cli", "client")
	clientConn, _ := client.admit(t, hub, address, "cli")
	hub.python.mu.Lock()
	hub.python.entries["shell:"] = entryAnswer{answer: map[string]any{
		"kind": "terminal", "device_id": "dev",
		"target": map[string]any{"session": agentSession, "open": map[string]any{"kind": "shell", "cols": 80, "rows": 24, "owner": "client:cli"}},
	}}
	hub.python.entries["connect:files"] = entryAnswer{answer: map[string]any{
		"kind": "file", "device_id": "dev",
		"target": map[string]any{"session": agentSession, "open": map[string]any{"kind": "connect", "port": 445}},
	}}
	hub.python.mu.Unlock()

	shell, refusal := openStream(t, clientConn, session.KindShell, map[string]any{"device_id": "dev", "session_id": "sh1"})
	if refusal != nil {
		t.Fatalf("shell refused %v", refusal)
	}
	_, _ = shell.Stream.Write(session.EncodeRecord(session.RecordData, []byte("ls")))
	rec, err := session.ReadRecord(shell.Reader)
	if err != nil || rec.Type != session.RecordData || string(rec.Payload) != "echo:ls" {
		t.Fatalf("shell echo %v %v", rec, err)
	}
	other, refusal := openStream(t, clientConn, session.KindShell, map[string]any{"device_id": "dev", "session_id": "sh2"})
	if refusal != nil {
		t.Fatalf("second shell refused %v", refusal)
	}
	files, refusal := openStream(t, clientConn, session.KindConnect, map[string]any{"id": "files"})
	if refusal != nil {
		t.Fatalf("files refused %v", refusal)
	}

	hub.hub.StreamsClose("cli", "terminal", "dev", "", "sh1", "session_not_owned", map[string]any{"session_id": "sh1"})
	rec, err = session.ReadRecord(shell.Reader)
	if err != nil || rec.Type != session.RecordClose {
		t.Fatalf("closed shell read %v %v", rec, err)
	}
	if closed, _ := session.ParseClose(rec.Payload); closed.Code != "session_not_owned" {
		t.Fatalf("close %v", closed)
	}
	_, _ = other.Stream.Write(session.EncodeRecord(session.RecordData, []byte("x")))
	if rec, err := session.ReadRecord(other.Reader); err != nil || string(rec.Payload) != "echo:x" {
		t.Fatalf("the other shell was touched: %v %v", rec, err)
	}

	agentConn.session.Close()
	rec, err = session.ReadRecord(other.Reader)
	if err != nil || rec.Type != session.RecordClose {
		t.Fatalf("after the agent left: %v %v", rec, err)
	}
	if closed, _ := session.ParseClose(rec.Payload); closed.Code != session.CodeAgentOffline || closed.Params["device"] != "dev" {
		t.Fatalf("close %v", closed)
	}
	_ = files.Stream.(*yamux.Stream).SetReadDeadline(time.Now().Add(5 * time.Second))
	if _, err := files.Reader.ReadByte(); err == nil {
		t.Fatal("the files stream stayed open after the agent left")
	}
}

func TestUdpConnectDialledByTheHub(t *testing.T) {
	hub := newTestHub(t)
	address := hub.listen(t)
	client := newPeer(t, hub, "cli", "client")
	clientConn, _ := client.admit(t, hub, address, "cli")
	echo, err := net.ListenUDP("udp", &net.UDPAddr{IP: net.IPv4(127, 0, 0, 1)})
	if err != nil {
		t.Fatal(err)
	}
	defer echo.Close()
	go func() {
		buffer := make([]byte, 2048)
		for {
			n, from, err := echo.ReadFromUDP(buffer)
			if err != nil {
				return
			}
			_, _ = echo.WriteToUDP(append([]byte("re:"), buffer[:n]...), from)
		}
	}()
	hub.python.mu.Lock()
	hub.python.entries["connect:dns"] = entryAnswer{answer: map[string]any{
		"kind": "port", "device_id": "",
		"target": map[string]any{"address": "127.0.0.1", "port": echo.LocalAddr().(*net.UDPAddr).Port, "protocol": "udp"},
	}}
	hub.python.mu.Unlock()
	record, refusal := openStream(t, clientConn, session.KindConnect, map[string]any{"id": "dns"})
	if refusal != nil {
		t.Fatalf("refused %v", refusal)
	}
	for _, source := range []uint16{40000, 40001} {
		datagram := make([]byte, 2)
		binary.BigEndian.PutUint16(datagram, source)
		datagram = append(datagram, []byte("q")...)
		_, _ = record.Stream.Write(session.EncodeRecord(session.RecordDatagram, datagram))
	}
	seen := map[uint16]string{}
	for i := 0; i < 2; i++ {
		rec, err := session.ReadRecord(record.Reader)
		if err != nil || rec.Type != session.RecordDatagram {
			t.Fatalf("reply %v %v", rec, err)
		}
		seen[binary.BigEndian.Uint16(rec.Payload)] = string(rec.Payload[2:])
	}
	if seen[40000] != "re:q" || seen[40001] != "re:q" {
		t.Fatalf("replies %v", seen)
	}
	_, _ = record.Stream.Write(session.EncodeRecord(session.RecordDatagram, []byte{1}))
	record.Stream.Close()
}

func TestStreamsCloseByRow(t *testing.T) {
	hub := newTestHub(t)
	address := hub.listen(t)
	client := newPeer(t, hub, "cli", "client")
	clientConn, _ := client.admit(t, hub, address, "cli")
	port := echoServer(t)
	hub.python.mu.Lock()
	for _, row := range []string{"row-a", "row-b"} {
		hub.python.entries["connect:"+row] = entryAnswer{answer: map[string]any{
			"kind": "web", "device_id": "dev", "key": row,
			"target": map[string]any{"address": "127.0.0.1", "port": port, "protocol": "tcp"},
		}}
	}
	hub.python.mu.Unlock()

	first, refusal := openStream(t, clientConn, session.KindConnect, map[string]any{"id": "row-a"})
	if refusal != nil {
		t.Fatalf("row-a refused %v", refusal)
	}
	second, refusal := openStream(t, clientConn, session.KindConnect, map[string]any{"id": "row-b"})
	if refusal != nil {
		t.Fatalf("row-b refused %v", refusal)
	}

	hub.hub.StreamsClose("cli", "web", "dev", "row-a", "", "permission_denied", map[string]any{"kind": "web"})
	_ = first.Stream.(*yamux.Stream).SetReadDeadline(time.Now().Add(5 * time.Second))
	if _, err := first.Reader.ReadByte(); err == nil {
		t.Fatal("the stream of the row switched off stayed open")
	}
	_, _ = second.Stream.Write([]byte("ping"))
	buffer := make([]byte, 4)
	_ = second.Stream.(*yamux.Stream).SetReadDeadline(time.Now().Add(5 * time.Second))
	if _, err := io.ReadFull(second.Reader, buffer); err != nil || string(buffer) != "ping" {
		t.Fatalf("the other row's stream was touched: %q %v", buffer, err)
	}
}

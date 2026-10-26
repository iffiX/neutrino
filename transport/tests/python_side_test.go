// Package tests runs a hub's transport and the peers' transports together
// over loopback, with the Python of each faked on its local channel.
package tests

import (
	"bufio"
	"encoding/json"
	"net"
	"strconv"
	"sync"
	"testing"
	"time"
)

// pythonSide is one faked Python on a local channel: it sends commands and
// frames, answers questions through a handler, and collects events and
// frames.
type pythonSide struct {
	t       *testing.T
	conn    net.Conn
	reader  *bufio.Reader
	writeMu sync.Mutex

	// mu guards pending and nextID.
	mu      sync.Mutex
	pending map[string]chan map[string]any
	nextID  int

	// answer answers a question's fields, or returns a refusal as {code, params}.
	answer func(question string, fields map[string]any) map[string]any
	events chan map[string]any
	frames chan map[string]any
}

// connectPython opens a control connection with the secret.
func connectPython(t *testing.T, path, secret string, answer func(string, map[string]any) map[string]any) *pythonSide {
	t.Helper()
	conn, err := net.DialTimeout("unix", path, 5*time.Second)
	if err != nil {
		t.Fatal(err)
	}
	side := &pythonSide{
		t: t, conn: conn, reader: bufio.NewReaderSize(conn, 4*1024*1024),
		pending: make(map[string]chan map[string]any), answer: answer,
		events: make(chan map[string]any, 256), frames: make(chan map[string]any, 256),
	}
	side.write(map[string]any{"secret": secret, "op": "control"})
	go side.read()
	t.Cleanup(func() { conn.Close() })
	return side
}

func (p *pythonSide) write(object map[string]any) {
	line, err := json.Marshal(object)
	if err != nil {
		p.t.Fatal(err)
	}
	p.writeMu.Lock()
	defer p.writeMu.Unlock()
	_, _ = p.conn.Write(append(line, '\n'))
}

func (p *pythonSide) read() {
	for {
		line, err := p.reader.ReadBytes('\n')
		if err != nil {
			return
		}
		var object map[string]any
		if err := json.Unmarshal(line, &object); err != nil {
			continue
		}
		switch {
		case object["question"] != nil:
			go p.answerQuestion(object)
		case object["event"] != nil:
			p.events <- object
		case object["frame"] != nil:
			p.frames <- object
		case object["id"] != nil:
			id, _ := object["id"].(string)
			p.mu.Lock()
			channel, ok := p.pending[id]
			delete(p.pending, id)
			p.mu.Unlock()
			if ok {
				channel <- object
			}
		}
	}
}

func (p *pythonSide) answerQuestion(question map[string]any) {
	id, _ := question["id"].(string)
	name, _ := question["question"].(string)
	reply := map[string]any{"id": id}
	if p.answer != nil {
		for key, value := range p.answer(name, question) {
			reply[key] = value
		}
	} else {
		reply["code"] = "unanswered"
	}
	p.write(reply)
}

// command sends a command and waits for its answer.
func (p *pythonSide) command(name string, fields map[string]any) map[string]any {
	p.t.Helper()
	p.mu.Lock()
	p.nextID++
	id := "c" + strconv.Itoa(p.nextID)
	channel := make(chan map[string]any, 1)
	p.pending[id] = channel
	p.mu.Unlock()
	line := map[string]any{"id": id, "command": name}
	for key, value := range fields {
		line[key] = value
	}
	p.write(line)
	select {
	case answer := <-channel:
		return answer
	case <-time.After(30 * time.Second):
		p.t.Fatalf("no answer to %s", name)
		return nil
	}
}

// frame writes a frame line with the key given, "session" or "binding", or
// none.
func (p *pythonSide) frame(frame map[string]any, key, value string) {
	line := map[string]any{"frame": frame}
	if key != "" {
		line[key] = value
	}
	p.write(line)
}

// waitEvent returns the next event of a name.
func (p *pythonSide) waitEvent(name string) map[string]any {
	p.t.Helper()
	deadline := time.After(20 * time.Second)
	for {
		select {
		case event := <-p.events:
			if event["event"] == name {
				return event
			}
		case <-deadline:
			p.t.Fatalf("no %s event", name)
			return nil
		}
	}
}

// waitFrame returns the next frame of a type with its line.
func (p *pythonSide) waitFrame(frameType string) (map[string]any, map[string]any) {
	p.t.Helper()
	deadline := time.After(20 * time.Second)
	for {
		select {
		case line := <-p.frames:
			frame, _ := line["frame"].(map[string]any)
			if frame["type"] == frameType {
				return frame, line
			}
		case <-deadline:
			p.t.Fatalf("no %s frame", frameType)
			return nil, nil
		}
	}
}

// noEvent asserts no event of a name arrives within wait.
func (p *pythonSide) noEvent(name string, wait time.Duration) {
	p.t.Helper()
	deadline := time.After(wait)
	for {
		select {
		case event := <-p.events:
			if event["event"] == name {
				p.t.Fatalf("unexpected %s event: %v", name, event)
			}
		case <-deadline:
			return
		}
	}
}

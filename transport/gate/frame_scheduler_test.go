package gate

import (
	"context"
	"encoding/binary"
	"errors"
	"io"
	"net"
	"sync"
	"testing"
	"time"

	"github.com/libp2p/go-yamux/v4"
)

// fakeChannel takes messages and acknowledges them at a rate once released.
type fakeChannel struct {
	mu        sync.Mutex
	sent      [][]byte
	buffered  uint64
	threshold uint64
	low       func()
	// peak is the largest buffered amount a write left.
	peak uint64
}

func (c *fakeChannel) WriteDataChannel(p []byte, _ bool) (int, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.sent = append(c.sent, append([]byte(nil), p...))
	c.buffered += uint64(len(p))
	c.peak = max(c.peak, c.buffered)
	return len(p), nil
}

func (c *fakeChannel) BufferedAmount() uint64 {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.buffered
}

func (c *fakeChannel) SetBufferedAmountLowThreshold(threshold uint64) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.threshold = threshold
}

func (c *fakeChannel) OnBufferedAmountLow(f func()) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.low = f
}

// acknowledge takes n bytes off the buffered amount.
func (c *fakeChannel) acknowledge(n uint64) {
	c.mu.Lock()
	from := c.buffered
	c.buffered -= min(n, c.buffered)
	low := c.low
	isLow := from > c.threshold && c.buffered <= c.threshold
	c.mu.Unlock()
	if isLow && low != nil {
		low()
	}
}

// messages returns what was sent so far.
func (c *fakeChannel) messages() [][]byte {
	c.mu.Lock()
	defer c.mu.Unlock()
	return append([][]byte(nil), c.sent...)
}

// frame is one yamux frame: a data frame carries body.
func frame(frameType byte, flags uint16, id uint32, body []byte) []byte {
	out := make([]byte, yamuxHeaderBytes+len(body))
	out[1] = frameType
	binary.BigEndian.PutUint16(out[2:], flags)
	binary.BigEndian.PutUint32(out[4:], id)
	if frameType == yamuxTypeData {
		binary.BigEndian.PutUint32(out[8:], uint32(len(body)))
	}
	copy(out[yamuxHeaderBytes:], body)
	return out
}

// label names a frame by its stream and its body.
func label(frame []byte) string {
	id := binary.BigEndian.Uint32(frame[4:])
	return string(rune('0'+id)) + ":" + string(frame[yamuxHeaderBytes:])
}

// scheduled starts a scheduler on a fake channel that holds the bound until
// released.
func scheduled(t *testing.T) (*frameScheduler, *fakeChannel) {
	t.Helper()
	channel := &fakeChannel{buffered: GateBufferedBytesMax + 1}
	closed := make(chan struct{})
	t.Cleanup(func() { close(closed) })
	s := newFrameScheduler(channel, closed)
	go s.run()
	return s, channel
}

// sentAfter releases the channel and returns the labels of the frames sent
// once want of them are.
func sentAfter(t *testing.T, channel *fakeChannel, want int) []string {
	t.Helper()
	channel.acknowledge(GateBufferedBytesMax + 1)
	deadline := time.Now().Add(2 * time.Second)
	for len(channel.messages()) < want && time.Now().Before(deadline) {
		time.Sleep(5 * time.Millisecond)
	}
	var labels []string
	for _, message := range channel.messages() {
		labels = append(labels, label(message))
	}
	return labels
}

func TestScheduledFramesOrder(t *testing.T) {
	cases := []struct {
		name   string
		frames [][]byte
		want   []string
	}{
		{
			name: "frames with no data before queued data",
			frames: [][]byte{
				frame(yamuxTypeData, 0, 1, []byte("a")),
				frame(yamuxTypeWindowUpdate, 0, 3, nil),
				frame(2, 1, 0, nil),
			},
			want: []string{"3:", "0:", "1:a"},
		},
		{
			name: "streams in turn",
			frames: [][]byte{
				frame(yamuxTypeData, 0, 1, []byte("a")),
				frame(yamuxTypeData, 0, 1, []byte("b")),
				frame(yamuxTypeData, 0, 1, []byte("c")),
				frame(yamuxTypeData, 0, 3, []byte("x")),
			},
			want: []string{"1:a", "3:x", "1:b", "1:c"},
		},
		{
			name: "a FIN after its stream's data",
			frames: [][]byte{
				frame(yamuxTypeData, 0, 1, []byte("a")),
				frame(yamuxTypeWindowUpdate, yamuxFlagFIN, 1, nil),
				frame(yamuxTypeData, 0, 3, []byte("x")),
			},
			want: []string{"1:a", "3:x", "1:"},
		},
		{
			name: "a reset drops its stream's frames",
			frames: [][]byte{
				frame(yamuxTypeData, 0, 1, []byte("a")),
				frame(yamuxTypeData, 0, 3, []byte("x")),
				frame(yamuxTypeWindowUpdate, yamuxFlagRST, 1, nil),
			},
			want: []string{"1:", "3:x"},
		},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			s, channel := scheduled(t)
			for _, f := range tc.frames {
				if _, err := s.write(f); err != nil {
					t.Fatal(err)
				}
			}
			time.Sleep(20 * time.Millisecond)
			got := sentAfter(t, channel, len(tc.want))
			if len(got) != len(tc.want) {
				t.Fatalf("sent %v, want %v", got, tc.want)
			}
			for i := range got {
				if got[i] != tc.want[i] {
					t.Fatalf("sent %v, want %v", got, tc.want)
				}
			}
		})
	}
}

func TestScheduledFramesJoinPieces(t *testing.T) {
	s, channel := scheduled(t)
	whole := frame(yamuxTypeData, 0, 1, []byte("abcdef"))
	if _, err := s.write(whole[:5]); err != nil {
		t.Fatal(err)
	}
	if _, err := s.write(whole[5:15]); err != nil {
		t.Fatal(err)
	}
	if _, err := s.write(whole[15:]); err != nil {
		t.Fatal(err)
	}
	if got := sentAfter(t, channel, 1); len(got) != 1 || got[0] != "1:abcdef" {
		t.Fatalf("sent %v", got)
	}
}

func TestScheduledWriteRefusesWhatIsNoFrame(t *testing.T) {
	s, _ := scheduled(t)
	bad := frame(yamuxTypeData, 0, 1, []byte("a"))
	bad[0] = 1
	if _, err := s.write(bad); !errors.Is(err, ErrYamuxFrameMalformed) {
		t.Fatalf("a frame of version 1: %v", err)
	}
	s2, _ := scheduled(t)
	if _, err := s2.write(frame(yamuxTypeData, 0, 1, make([]byte, GateMessageBytesMax))); !errors.Is(err, ErrYamuxFrameMalformed) {
		t.Fatalf("a frame past the message size: %v", err)
	}
}

func TestScheduledFramesKeepTheChannelUnderTheBound(t *testing.T) {
	channel := &fakeChannel{}
	closed := make(chan struct{})
	defer close(closed)
	s := newFrameScheduler(channel, closed)
	go s.run()
	body := make([]byte, 60*1024)
	for i := 0; i < 40; i++ {
		if _, err := s.write(frame(yamuxTypeData, 0, uint32(1+2*(i%4)), body)); err != nil {
			t.Fatal(err)
		}
	}
	deadline := time.Now().Add(5 * time.Second)
	for len(channel.messages()) < 40 && time.Now().Before(deadline) {
		time.Sleep(2 * time.Millisecond)
		channel.acknowledge(16 * 1024)
	}
	if len(channel.messages()) != 40 {
		t.Fatalf("sent %d frames of 40", len(channel.messages()))
	}
	if limit := uint64(GateBufferedBytesMax + yamuxHeaderBytes + len(body)); channel.peak > limit {
		t.Fatalf("the channel held %d bytes, over %d", channel.peak, limit)
	}
}

// slowConn writes at most bps bytes a second.
type slowConn struct {
	net.Conn
	bps int
}

func (c *slowConn) Write(p []byte) (int, error) {
	time.Sleep(time.Duration(len(p)) * time.Second / time.Duration(c.bps))
	return c.Conn.Write(p)
}

// guestPair opens a gate channel whose hub writes at most bps bytes a second,
// with yamux on it: the hub's session as the hub runs it, the guest's with a
// fixed window per stream.
func guestPair(t *testing.T, bps int, window uint32) (*yamux.Session, *yamux.Session, *ChannelConn) {
	t.Helper()
	g := testGate(t)
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { listener.Close() })
	results := make(chan openResult, 1)
	go func() {
		conn, err := listener.Accept()
		if err != nil {
			results <- openResult{err: err}
			return
		}
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		check, err := g.ReadFirstCheck(conn)
		if err != nil {
			results <- openResult{err: err}
			return
		}
		channel, _, err := g.Open(ctx, &slowConn{Conn: conn, bps: bps}, check)
		results <- openResult{conn: channel, err: err}
	}()
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	client, err := Dial(ctx, listener.Addr().String(), DialOptions{Ufrag: testUfrag, Password: testPassword, Fingerprint: g.Fingerprint()})
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { client.Close() })
	result := <-results
	if result.err != nil {
		t.Fatal(result.err)
	}
	t.Cleanup(func() { result.conn.Close() })
	result.conn.ScheduleFrames()
	hubConfig := yamux.DefaultConfig()
	hubConfig.LogOutput = io.Discard
	hubConfig.MaxMessageSize = 64*1024 - 17
	hubConfig.EnableKeepAlive = false
	hub, err := yamux.Server(result.conn, hubConfig, nil)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { hub.Close() })
	guestConfig := yamux.DefaultConfig()
	guestConfig.LogOutput = io.Discard
	guestConfig.InitialStreamWindowSize = window
	guestConfig.MaxStreamWindowSize = window
	guestConfig.EnableKeepAlive = false
	guest, err := yamux.Client(client, guestConfig, nil)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { guest.Close() })
	return hub, guest, result.conn
}

func TestScheduledBytesStayInTheGrantedWindows(t *testing.T) {
	const window = 512 * 1024
	const streams = 4
	hub, guest, channel := guestPair(t, 128*1024, window)
	go func() {
		for {
			stream, err := hub.AcceptStream()
			if err != nil {
				return
			}
			go func() {
				chunk := make([]byte, 64*1024)
				for {
					if _, err := stream.Write(chunk); err != nil {
						return
					}
				}
			}()
		}
	}()
	for i := 0; i < streams; i++ {
		stream, err := guest.OpenStream(context.Background())
		if err != nil {
			t.Fatal(err)
		}
		if _, err := stream.Write([]byte("open")); err != nil {
			t.Fatal(err)
		}
	}
	time.Sleep(2 * time.Second)
	held := uint64(channel.scheduledBytes()) + channel.channel.BufferedAmount()
	if limit := uint64(streams * (window + 2*64*1024)); held > limit {
		t.Fatalf("the hub held %d bytes for a guest that reads nothing, over %d", held, limit)
	}
	if held < streams*window/2 {
		t.Fatalf("the hub held only %d bytes; the streams did not fill their windows", held)
	}
}

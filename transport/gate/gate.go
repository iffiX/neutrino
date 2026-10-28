package gate

import (
	"bufio"
	"context"
	"crypto/tls"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"net"
	"strings"
	"sync"
	"time"

	"github.com/pion/datachannel"
	"github.com/pion/dtls/v3"
	"github.com/pion/logging"
	"github.com/pion/sctp"
	"github.com/pion/stun/v3"
)

// Share is one live share's ICE pair, as the Python sends it.
type Share struct {
	Ufrag    string `json:"ufrag"`
	Password string `json:"pwd"`
}

// Decision is where the hub decided a browser's first connectivity check.
type Decision struct {
	// FrameBytes is the length of the first frame on the wire, its two
	// length bytes included.
	FrameBytes int
	// UsernameEndByte is the byte, counted from the first on the wire, at
	// which the USERNAME attribute ended and the share was looked up.
	UsernameEndByte int
}

// Gate is the hub's WebRTC gate: its DTLS certificate and the live shares'
// ICE pairs.
type Gate struct {
	logger logging.LoggerFactory

	// mu guards certificate, fingerprint and shares.
	mu          sync.RWMutex
	certificate tls.Certificate
	fingerprint string
	shares      map[string]string
}

// FirstCheck is a connection's first connectivity check, verified.
type FirstCheck struct {
	message  *stun.Message
	ufrag    string
	password string
	// Decision is where the hub decided the check.
	Decision Decision
}

// New makes a gate under certificate with no live share.
func New(certificate tls.Certificate) *Gate {
	logger := logging.NewDefaultLoggerFactory()
	logger.Writer = io.Discard
	logger.DefaultLogLevel = logging.LogLevelDisabled
	return &Gate{logger: logger, certificate: certificate, fingerprint: Fingerprint(certificate), shares: map[string]string{}}
}

// Fingerprint is the certificate's, as a link carries it.
func (g *Gate) Fingerprint() string {
	g.mu.RLock()
	defer g.mu.RUnlock()
	return g.fingerprint
}

// SetCertificate replaces the certificate; connections already open keep
// the one they were opened under.
func (g *Gate) SetCertificate(certificate tls.Certificate) {
	g.mu.Lock()
	defer g.mu.Unlock()
	g.certificate = certificate
	g.fingerprint = Fingerprint(certificate)
}

// SetShares replaces the live shares with shares.
func (g *Gate) SetShares(shares []Share) {
	table := make(map[string]string, len(shares))
	for _, share := range shares {
		if share.Ufrag != "" && share.Password != "" {
			table[share.Ufrag] = share.Password
		}
	}
	g.mu.Lock()
	defer g.mu.Unlock()
	g.shares = table
}

// HasShares reports whether any share is live, which is when the gate
// reads a browser's connection at all.
func (g *Gate) HasShares() bool {
	g.mu.RLock()
	defer g.mu.RUnlock()
	return len(g.shares) > 0
}

// ReadFirstCheck reads a connection's first frame from r as far as it fits
// a Binding Request for a live share, and no further: the frame length, the
// STUN type and length, the magic cookie, the USERNAME's ufrag against the
// live shares, then the rest of the frame and its integrity and
// fingerprint. It reads every byte through r, whose deadline the caller
// sets, and writes nothing. It returns ErrNotStun, ErrShareUnknown or
// ErrStunRefused at the first check that fails.
func (g *Gate) ReadFirstCheck(r io.Reader) (*FirstCheck, error) {
	var head [GatePeekBytes]byte
	if _, err := io.ReadFull(r, head[:GateFrameLengthBytes]); err != nil {
		return nil, fmt.Errorf("%w: %w", ErrNotStun, err)
	}
	if head[0] != GateFrameFirstByte {
		return nil, fmt.Errorf("%w: first byte %d", ErrNotStun, head[0])
	}
	length := int(head[1])
	if length < GateStunHeaderBytes {
		return nil, fmt.Errorf("%w: frame of %d bytes", ErrNotStun, length)
	}
	if _, err := io.ReadFull(r, head[GateFrameLengthBytes:6]); err != nil {
		return nil, fmt.Errorf("%w: %w", ErrNotStun, err)
	}
	if binary.BigEndian.Uint16(head[2:4]) != GateStunBindingRequestType {
		return nil, fmt.Errorf("%w: type %x", ErrNotStun, head[2:4])
	}
	if int(binary.BigEndian.Uint16(head[4:6])) != length-GateStunHeaderBytes {
		return nil, fmt.Errorf("%w: stun length", ErrNotStun)
	}
	if _, err := io.ReadFull(r, head[6:GatePeekBytes]); err != nil {
		return nil, fmt.Errorf("%w: %w", ErrNotStun, err)
	}
	if binary.BigEndian.Uint32(head[6:GatePeekBytes]) != GateStunMagicCookie {
		return nil, fmt.Errorf("%w: cookie", ErrNotStun)
	}
	frame := make([]byte, length)
	copy(frame, head[GateFrameLengthBytes:GatePeekBytes])
	ufrag, usernameEnd, err := readToUsername(r, frame)
	if err != nil {
		return nil, err
	}
	decision := Decision{FrameBytes: GateFrameLengthBytes + length, UsernameEndByte: GateFrameLengthBytes + usernameEnd}
	g.mu.RLock()
	password, isLive := g.shares[ufrag]
	g.mu.RUnlock()
	if !isLive {
		return nil, fmt.Errorf("%w: %s", ErrShareUnknown, ufrag)
	}
	if _, err := io.ReadFull(r, frame[usernameEnd:]); err != nil {
		return nil, fmt.Errorf("%w: %w", ErrNotStun, err)
	}
	message := &stun.Message{Raw: frame}
	if err := message.Decode(); err != nil || message.Type != stun.BindingRequest {
		return nil, fmt.Errorf("%w: decode", ErrNotStun)
	}
	if err := verifyCheck(message, password); err != nil {
		return nil, err
	}
	return &FirstCheck{message: message, ufrag: ufrag, password: password, Decision: decision}, nil
}

// Open runs the gate on one accepted connection whose first check passed:
// it answers the check, clears the connection's deadline, then runs the
// DTLS handshake, the SCTP association and data channel 0 under ctx. It
// returns the channel as a connection and the ufrag of the share it was
// opened under. It returns the handshake's error, or ctx's error when ctx
// ends first. The connection is closed on every error.
func (g *Gate) Open(ctx context.Context, conn net.Conn, check *FirstCheck) (*ChannelConn, string, error) {
	_ = conn.SetReadDeadline(time.Time{})
	reader := bufio.NewReaderSize(conn, GateFrameLengthBytes+GateFrameBytesMax)
	answerer := &stunAnswerer{ufrag: check.ufrag, password: check.password, peer: tcpAddr(conn.RemoteAddr())}
	framed := newFramedConn(&readerConn{Conn: conn, reader: reader}, answerer.handle)
	answerer.write = framed.WriteFrame
	go framed.run()
	if deadline, ok := ctx.Deadline(); ok {
		_ = framed.SetReadDeadline(deadline)
	}
	if err := answerer.answer(check.message); err != nil {
		framed.Close()
		return nil, "", fmt.Errorf("stun answer: %w", err)
	}
	g.mu.RLock()
	certificate := g.certificate
	g.mu.RUnlock()
	dtlsConn, err := dtls.ServerWithOptions(framed, conn.RemoteAddr(),
		dtls.WithCertificates(certificate),
		dtls.WithClientAuth(dtls.NoClientCert),
		dtls.WithExtendedMasterSecret(dtls.RequireExtendedMasterSecret),
		dtls.WithMTU(GateMTU),
		dtls.WithLoggerFactory(g.logger),
		dtls.WithSRTPProtectionProfiles(dtls.SRTP_AEAD_AES_128_GCM, dtls.SRTP_AES128_CM_HMAC_SHA1_80),
	)
	if err != nil {
		framed.Close()
		return nil, "", fmt.Errorf("dtls: %w", err)
	}
	if err := dtlsConn.HandshakeContext(ctx); err != nil {
		framed.Close()
		return nil, "", fmt.Errorf("dtls handshake: %w", err)
	}
	channel, err := openChannel(dtlsConn, serverAssociation, g.logger)
	if err != nil {
		dtlsConn.Close()
		framed.Close()
		return nil, "", err
	}
	_ = framed.SetReadDeadline(time.Time{})
	return newChannelConn(channel, conn, dtlsConn, framed), check.ufrag, nil
}

// readToUsername reads a first frame's attributes into frame, after the
// header's first eight bytes already there, up to the end of its USERNAME.
// It returns the ufrag and the offset in frame where the USERNAME ended, or
// ErrNotStun for a frame with no USERNAME of the form ufrag:peer.
func readToUsername(reader io.Reader, frame []byte) (string, int, error) {
	if _, err := io.ReadFull(reader, frame[GatePeekBytes-GateFrameLengthBytes:GateStunHeaderBytes]); err != nil {
		return "", 0, fmt.Errorf("%w: %w", ErrNotStun, err)
	}
	offset := GateStunHeaderBytes
	for offset+GateStunAttributeHeaderBytes <= len(frame) {
		valueStart := offset + GateStunAttributeHeaderBytes
		if _, err := io.ReadFull(reader, frame[offset:valueStart]); err != nil {
			return "", 0, fmt.Errorf("%w: %w", ErrNotStun, err)
		}
		attributeType := binary.BigEndian.Uint16(frame[offset:])
		valueEnd := valueStart + int(binary.BigEndian.Uint16(frame[offset+2:]))
		if valueEnd > len(frame) {
			return "", 0, fmt.Errorf("%w: attribute length", ErrNotStun)
		}
		if attributeType == GateStunUsernameType {
			if _, err := io.ReadFull(reader, frame[valueStart:valueEnd]); err != nil {
				return "", 0, fmt.Errorf("%w: %w", ErrNotStun, err)
			}
			ufrag, _, isPair := strings.Cut(string(frame[valueStart:valueEnd]), ":")
			if !isPair || ufrag == "" {
				return "", 0, fmt.Errorf("%w: username", ErrNotStun)
			}
			return ufrag, valueEnd, nil
		}
		next := min(valueStart+(valueEnd-valueStart+3)&^3, len(frame))
		if _, err := io.ReadFull(reader, frame[valueStart:next]); err != nil {
			return "", 0, fmt.Errorf("%w: %w", ErrNotStun, err)
		}
		offset = next
	}
	return "", 0, fmt.Errorf("%w: no username", ErrNotStun)
}

// openChannel runs the SCTP association with associate over the DTLS
// connection and opens data channel 0, negotiated; the association's other
// streams are closed as they come.
func openChannel(dtlsConn net.Conn, associate func(...sctp.AssociationOption) (*sctp.Association, error), logger logging.LoggerFactory) (*datachannel.DataChannel, error) {
	association, err := associate(
		sctp.WithNetConn(dtlsConn),
		sctp.WithLoggerFactory(logger),
		sctp.WithMTU(GateMTU-GateSctpOverheadBytes),
		sctp.WithMaxReceiveBufferSize(GateReceiveBufferBytes),
	)
	if err != nil {
		return nil, fmt.Errorf("sctp: %w", err)
	}
	channel, err := datachannel.Dial(association, GateChannelID, &datachannel.Config{
		Negotiated:    true,
		ChannelType:   datachannel.ChannelTypeReliable,
		Label:         GateChannelLabel,
		LoggerFactory: logger,
	})
	if err != nil {
		association.Abort("channel")
		return nil, fmt.Errorf("data channel: %w", err)
	}
	go closeOtherStreams(association)
	return channel, nil
}

// serverAssociation is the hub's side of the SCTP association.
func serverAssociation(options ...sctp.AssociationOption) (*sctp.Association, error) {
	serverOptions := make([]sctp.ServerOption, len(options))
	for i, option := range options {
		serverOptions[i] = option
	}
	return sctp.ServerWithOptions(serverOptions...)
}

// closeOtherStreams closes every stream the peer opens beside channel 0,
// until the association ends.
func closeOtherStreams(association *sctp.Association) {
	for {
		stream, err := association.AcceptStream()
		if err != nil {
			return
		}
		stream.Close()
	}
}

// readerConn reads what its reader already holds before the connection.
type readerConn struct {
	net.Conn
	reader *bufio.Reader
}

func (c *readerConn) Read(p []byte) (int, error) {
	return c.reader.Read(p)
}

// isClosed reports whether an error is the end of a closed connection.
func isClosed(err error) bool {
	return errors.Is(err, net.ErrClosed) || errors.Is(err, io.EOF)
}

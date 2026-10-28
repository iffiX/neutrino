package gate

import (
	"context"
	"crypto/x509"
	"fmt"
	"net"
	"time"

	"github.com/pion/dtls/v3"
	"github.com/pion/logging"
	"github.com/pion/sctp"
	"github.com/pion/stun/v3"
)

// DialOptions is what a dial of the gate needs: the share's ICE pair and
// the hub's certificate fingerprint, as a link carries them.
type DialOptions struct {
	Ufrag       string
	Password    string
	Fingerprint string
	// Timeout bounds the connect and the handshakes together;
	// GateDialTimeout when zero.
	Timeout time.Duration
}

// Dial connects to address as a browser does: one connectivity check under
// the share's pair, the DTLS handshake as the client with the hub's
// certificate checked against Fingerprint, the SCTP association and data
// channel 0. It returns the channel as a connection, ErrStunRefused when the
// hub does not answer the check, ErrFingerprintMismatch when the hub's
// certificate is another, and the connection's own error otherwise,
// context.DeadlineExceeded among them.
func Dial(ctx context.Context, address string, options DialOptions) (*ChannelConn, error) {
	timeout := options.Timeout
	if timeout == 0 {
		timeout = GateDialTimeout
	}
	ctx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	var dialer net.Dialer
	conn, err := dialer.DialContext(ctx, "tcp", address)
	if err != nil {
		return nil, fmt.Errorf("dial %s: %w", address, err)
	}
	answers := make(chan []byte, 4)
	framed := newFramedConn(conn, func(frame []byte) {
		select {
		case answers <- frame:
		default:
		}
	})
	go framed.run()
	if deadline, ok := ctx.Deadline(); ok {
		_ = framed.SetReadDeadline(deadline)
	}
	request, err := stun.Build(stun.TransactionID, stun.BindingRequest,
		stun.NewUsername(options.Ufrag+":"+GateClientUfrag),
		stun.NewShortTermIntegrity(options.Password), stun.Fingerprint)
	if err != nil {
		framed.Close()
		return nil, err
	}
	if err := framed.WriteFrame(request.Raw); err != nil {
		framed.Close()
		return nil, fmt.Errorf("stun request: %w", err)
	}
	select {
	case frame := <-answers:
		answer := &stun.Message{Raw: frame}
		if err := answer.Decode(); err != nil || answer.Type != stun.BindingSuccess ||
			stun.NewShortTermIntegrity(options.Password).Check(answer) != nil {
			framed.Close()
			return nil, ErrStunRefused
		}
	case <-ctx.Done():
		framed.Close()
		return nil, fmt.Errorf("%w: %w", ErrStunRefused, ctx.Err())
	case <-framed.closed:
		return nil, fmt.Errorf("%w: connection closed", ErrStunRefused)
	}
	logger := logging.NewDefaultLoggerFactory()
	logger.DefaultLogLevel = logging.LogLevelDisabled
	dtlsConn, err := dtls.ClientWithOptions(framed, conn.RemoteAddr(),
		dtls.WithInsecureSkipVerify(true),
		dtls.WithVerifyPeerCertificate(func(raw [][]byte, _ [][]*x509.Certificate) error {
			if len(raw) == 0 || FingerprintOf(raw[0]) != options.Fingerprint {
				return ErrFingerprintMismatch
			}
			return nil
		}),
		dtls.WithExtendedMasterSecret(dtls.RequireExtendedMasterSecret),
		dtls.WithMTU(GateMTU),
		dtls.WithLoggerFactory(logger),
		dtls.WithSRTPProtectionProfiles(dtls.SRTP_AEAD_AES_128_GCM, dtls.SRTP_AES128_CM_HMAC_SHA1_80),
	)
	if err != nil {
		framed.Close()
		return nil, fmt.Errorf("dtls: %w", err)
	}
	if err := dtlsConn.HandshakeContext(ctx); err != nil {
		framed.Close()
		return nil, fmt.Errorf("dtls handshake: %w", err)
	}
	channel, err := openChannel(dtlsConn, clientAssociation, logger)
	if err != nil {
		dtlsConn.Close()
		framed.Close()
		return nil, err
	}
	_ = framed.SetReadDeadline(time.Time{})
	return newChannelConn(channel, conn, dtlsConn, framed), nil
}

// clientAssociation is the client's side of the SCTP association, in the
// server's shape.
func clientAssociation(options ...sctp.AssociationOption) (*sctp.Association, error) {
	clientOptions := make([]sctp.ClientOption, len(options))
	for i, option := range options {
		clientOptions[i] = option
	}
	return sctp.ClientWithOptions(clientOptions...)
}

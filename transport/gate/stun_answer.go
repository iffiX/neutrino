package gate

import (
	"encoding/binary"
	"net"
	"strings"

	"github.com/pion/stun/v3"
)

// stunAnswerer answers the later connectivity checks of one connection
// under the share its first check named, for as long as the connection
// lives.
type stunAnswerer struct {
	ufrag    string
	password string
	peer     *net.TCPAddr
	write    func(frame []byte) error
}

// handle answers one STUN frame after the first: a Binding Request whose
// USERNAME names the connection's share and whose MESSAGE-INTEGRITY and
// FINGERPRINT verify gets a Binding Success; every other frame is dropped.
func (a *stunAnswerer) handle(frame []byte) {
	message := &stun.Message{Raw: frame}
	if err := message.Decode(); err != nil || message.Type != stun.BindingRequest {
		return
	}
	ufrag, _, isFound := usernameOf(frame)
	if !isFound || ufrag != a.ufrag {
		return
	}
	if err := verifyCheck(message, a.password); err != nil {
		return
	}
	_ = a.answer(message)
}

// answer writes the Binding Success for one verified request: the peer's
// address, the integrity under the share's password and the fingerprint.
func (a *stunAnswerer) answer(request *stun.Message) error {
	response, err := stun.Build(request, stun.BindingSuccess,
		&stun.XORMappedAddress{IP: a.peer.IP, Port: a.peer.Port},
		stun.NewShortTermIntegrity(a.password), stun.Fingerprint)
	if err != nil {
		return err
	}
	return a.write(response.Raw)
}

// verifyCheck checks a Binding Request's MESSAGE-INTEGRITY under password
// and its FINGERPRINT. It returns ErrStunRefused when either fails.
func verifyCheck(message *stun.Message, password string) error {
	if err := stun.NewShortTermIntegrity(password).Check(message); err != nil {
		return ErrStunRefused
	}
	if err := stun.Fingerprint.Check(message); err != nil {
		return ErrStunRefused
	}
	return nil
}

// usernameOf walks a STUN message's attributes to its USERNAME and returns
// the part before the colon, the share's ufrag, and the byte at which the
// attribute ended. It returns false when the message has no USERNAME with
// a colon before its attributes end or run past the message.
func usernameOf(frame []byte) (string, int, bool) {
	offset := GateStunHeaderBytes
	for offset+GateStunAttributeHeaderBytes <= len(frame) {
		attributeType := binary.BigEndian.Uint16(frame[offset:])
		length := int(binary.BigEndian.Uint16(frame[offset+2:]))
		valueStart := offset + GateStunAttributeHeaderBytes
		if valueStart+length > len(frame) {
			return "", 0, false
		}
		if attributeType == GateStunUsernameType {
			ufrag, _, isPair := strings.Cut(string(frame[valueStart:valueStart+length]), ":")
			if !isPair || ufrag == "" {
				return "", 0, false
			}
			return ufrag, valueStart + length, true
		}
		offset = valueStart + (length+3)&^3
	}
	return "", 0, false
}

// tcpAddr is an address as a TCP address, the zero address when it is not
// one.
func tcpAddr(address net.Addr) *net.TCPAddr {
	if tcp, ok := address.(*net.TCPAddr); ok {
		return tcp
	}
	return &net.TCPAddr{IP: net.IPv4zero}
}

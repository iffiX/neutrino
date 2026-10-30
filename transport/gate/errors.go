package gate

import "errors"

var (
	// ErrFrameTooLarge is a frame past GateFrameBytesMax.
	ErrFrameTooLarge = errors.New("frame too large")
	// ErrNotStun is a first frame that is not a STUN Binding Request with a
	// USERNAME: the hub closes at the first byte that does not fit.
	ErrNotStun = errors.New("not a stun binding request")
	// ErrShareUnknown is an ice-ufrag no live share holds.
	ErrShareUnknown = errors.New("share unknown")
	// ErrStunRefused is a connectivity check whose integrity or fingerprint
	// does not verify, or an answer that does not.
	ErrStunRefused = errors.New("stun check refused")
	// ErrFingerprintMismatch is a hub certificate whose fingerprint is not
	// the link's.
	ErrFingerprintMismatch = errors.New("dtls fingerprint mismatch")
	// ErrGuestOpenMalformed is a first message that is not a guest's open
	// record.
	ErrGuestOpenMalformed = errors.New("guest open malformed")
	// ErrGuestAnswerMalformed is a hub's answer that is neither an accept
	// nor a close record.
	ErrGuestAnswerMalformed = errors.New("guest answer malformed")
	// ErrMessageTooLarge is a channel message past the buffer given.
	ErrMessageTooLarge = errors.New("channel message too large")
	// ErrYamuxFrameMalformed is a write to a channel that schedules frames
	// which is not a yamux frame of at most GateMessageBytesMax.
	ErrYamuxFrameMalformed = errors.New("yamux frame malformed")
)

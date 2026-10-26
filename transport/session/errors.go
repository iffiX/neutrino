package session

import "errors"

var (
	// ErrRecordTooLarge is a record whose payload is past RecordBytesMax.
	ErrRecordTooLarge = errors.New("record too large")
	// ErrFrameTooLarge is a control frame past ControlFrameBytesMax.
	ErrFrameTooLarge = errors.New("control frame too large")
	// ErrNoiseMessageTooLarge is a Noise message past NoiseMessageMax.
	ErrNoiseMessageTooLarge = errors.New("noise message too large")
	// ErrMemoryExhausted is a window the transport's memory cap refuses.
	ErrMemoryExhausted = errors.New("transport memory exhausted")
	// ErrSchemeUnknown is an address whose scheme the transport does not dial.
	ErrSchemeUnknown = errors.New("address scheme unknown")
	// ErrAnswerMalformed is a hub's answer that is neither message 2 nor a
	// cookie reply.
	ErrAnswerMalformed = errors.New("handshake answer malformed")
	// ErrStreamRefused is a stream whose first record is a refusing close.
	ErrStreamRefused = errors.New("stream refused")
	// ErrRecordUnexpected is a record where another type was due.
	ErrRecordUnexpected = errors.New("record unexpected")
)

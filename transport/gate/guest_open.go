package gate

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"

	"github.com/iffiX/neutrino/transport/session"
)

// GuestOpen is the payload of a guest's first record on the data channel:
// the channel number it speaks and the share ticket.
type GuestOpen struct {
	Protocol int    `json:"protocol"`
	Ticket   string `json:"ticket"`
}

// GuestOpenRecord is a guest's first message: one open record carrying the
// guest open.
func GuestOpenRecord(open GuestOpen) []byte {
	payload, err := json.Marshal(open)
	if err != nil {
		panic(err)
	}
	return session.EncodeRecord(session.RecordOpen, payload)
}

// ParseGuestOpen reads a guest's first message as an open record and
// returns its payload. It returns ErrGuestOpenMalformed for a message that
// is not one open record whose payload is the JSON object with a ticket.
func ParseGuestOpen(message []byte) (GuestOpen, error) {
	record, err := session.ReadRecord(bufio.NewReader(bytes.NewReader(message)))
	if err != nil || record.Type != session.RecordOpen {
		return GuestOpen{}, fmt.Errorf("%w: not an open record", ErrGuestOpenMalformed)
	}
	var open GuestOpen
	if err := json.Unmarshal(record.Payload, &open); err != nil {
		return GuestOpen{}, fmt.Errorf("%w: %w", ErrGuestOpenMalformed, err)
	}
	if open.Ticket == "" {
		return GuestOpen{}, fmt.Errorf("%w: no ticket", ErrGuestOpenMalformed)
	}
	return open, nil
}

// GuestAcceptRecord is the hub's answer that admits a guest: an accept
// record whose payload names the share's id, which the guest's hello then
// carries.
func GuestAcceptRecord(id string) []byte {
	payload, err := json.Marshal(map[string]string{"id": id})
	if err != nil {
		panic(err)
	}
	return session.EncodeRecord(session.RecordAccept, payload)
}

// GuestRefuseRecord is the hub's answer that refuses a guest: a close
// record with the refusal.
func GuestRefuseRecord(refusal *session.Refusal) []byte {
	return session.CloseRecord(refusal.Code, refusal.Params)
}

// ParseGuestAnswer reads the hub's answer to a guest open: the share's id
// for an accept, the refusal for a close. It returns
// ErrGuestAnswerMalformed for any other message.
func ParseGuestAnswer(message []byte) (string, *session.Refusal, error) {
	record, err := session.ReadRecord(bufio.NewReader(bytes.NewReader(message)))
	if err != nil {
		return "", nil, fmt.Errorf("%w: %w", ErrGuestAnswerMalformed, err)
	}
	switch record.Type {
	case session.RecordAccept:
		var accepted struct {
			ID string `json:"id"`
		}
		if err := json.Unmarshal(record.Payload, &accepted); err != nil || accepted.ID == "" {
			return "", nil, fmt.Errorf("%w: accept without an id", ErrGuestAnswerMalformed)
		}
		return accepted.ID, nil, nil
	case session.RecordClose:
		refusal, err := session.ParseClose(record.Payload)
		if err != nil {
			return "", nil, fmt.Errorf("%w: %w", ErrGuestAnswerMalformed, err)
		}
		return "", refusal, nil
	}
	return "", nil, fmt.Errorf("%w: record type %d", ErrGuestAnswerMalformed, record.Type)
}

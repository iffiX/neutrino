package knock

import (
	"encoding/json"
	"fmt"
)

// Payload is message 1's payload: what the peer says about itself before
// the hub knows whose key it holds.
type Payload struct {
	Protocol int    `json:"protocol"`
	Role     string `json:"role"`
	IsJoin   bool   `json:"is_join"`
	// Time is the peer's clock in Unix nanoseconds.
	Time int64 `json:"time"`
}

// Marshal writes the payload as the JSON message 1 carries.
func (p Payload) Marshal() []byte {
	data, err := json.Marshal(p)
	if err != nil {
		panic(err)
	}
	return data
}

// ParsePayload reads a payload and checks its role. It returns
// ErrKnockMalformed for bytes that are not the JSON object or a role that is
// neither agent nor client.
func ParsePayload(data []byte) (Payload, error) {
	var payload Payload
	if err := json.Unmarshal(data, &payload); err != nil {
		return Payload{}, fmt.Errorf("%w: payload: %w", ErrKnockMalformed, err)
	}
	if payload.Role != KnockRoleAgent && payload.Role != KnockRoleClient {
		return Payload{}, fmt.Errorf("%w: role %q", ErrKnockMalformed, payload.Role)
	}
	return payload, nil
}

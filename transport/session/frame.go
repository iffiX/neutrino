package session

import (
	"encoding/json"
	"fmt"
)

// FrameType reads the type of a frame, the JSON object a control stream's
// line holds. It returns an error for a line that is not an object with a
// string type.
func FrameType(frame []byte) (string, error) {
	var head struct {
		Type string `json:"type"`
	}
	if err := json.Unmarshal(frame, &head); err != nil {
		return "", fmt.Errorf("frame: %w", err)
	}
	if head.Type == "" {
		return "", fmt.Errorf("frame: no type")
	}
	return head.Type, nil
}

// MakeFrame writes a frame of frameType with fields.
func MakeFrame(frameType string, fields map[string]any) []byte {
	object := make(map[string]any, len(fields)+1)
	for key, value := range fields {
		object[key] = value
	}
	object[FrameTypeKey] = frameType
	frame, err := json.Marshal(object)
	if err != nil {
		panic(err)
	}
	return frame
}

// RefusedFrame is the refused frame of a refusal.
func RefusedFrame(refusal *Refusal) []byte {
	return MakeFrame(FrameRefused, map[string]any{"code": refusal.Code, "params": refusal.Params})
}

// PongFrame answers a ping frame: its nonce echoed, cut to PingNonceCharsMax,
// an empty string when the ping had none.
func PongFrame(ping []byte) []byte {
	var body struct {
		Nonce string `json:"nonce"`
	}
	_ = json.Unmarshal(ping, &body)
	nonce := body.Nonce
	if len(nonce) > PingNonceCharsMax {
		nonce = nonce[:PingNonceCharsMax]
	}
	return MakeFrame(FramePong, map[string]any{"nonce": nonce})
}

// ParseRefused reads a refused frame, or a reply, as a refusal: a frame with
// no code gives an empty Code.
func ParseRefused(frame []byte) *Refusal {
	var refusal Refusal
	_ = json.Unmarshal(frame, &refusal)
	if refusal.Params == nil {
		refusal.Params = map[string]any{}
	}
	return &refusal
}

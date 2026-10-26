package session

import (
	"bufio"
	"encoding/binary"
	"encoding/json"
	"fmt"
	"io"
)

// Record is one record of a stream: a type and a payload.
type Record struct {
	Type    byte
	Payload []byte
}

// Refusal is the {code, params} shape of a refusing close, a refused frame
// and a local answer.
type Refusal struct {
	Code   string         `json:"code"`
	Params map[string]any `json:"params,omitempty"`
}

// Error words the refusal, so a Refusal is an error a caller checks with
// errors.As.
func (r *Refusal) Error() string {
	return "refused " + r.Code
}

// NewRefusal makes a refusal with the params given, an empty object when
// none is.
func NewRefusal(code string, params map[string]any) *Refusal {
	if params == nil {
		params = map[string]any{}
	}
	return &Refusal{Code: code, Params: params}
}

// ReadRecord reads one record. It returns ErrRecordTooLarge for a payload past
// RecordBytesMax and the reader's error when the bytes end.
func ReadRecord(r *bufio.Reader) (Record, error) {
	var header [RecordHeaderBytes]byte
	if _, err := io.ReadFull(r, header[:]); err != nil {
		return Record{}, err
	}
	size := binary.BigEndian.Uint32(header[1:])
	if size > RecordBytesMax {
		return Record{}, fmt.Errorf("%w: %d bytes", ErrRecordTooLarge, size)
	}
	payload := make([]byte, size)
	if _, err := io.ReadFull(r, payload); err != nil {
		return Record{}, err
	}
	return Record{Type: header[0], Payload: payload}, nil
}

// EncodeRecord writes a record's bytes: the type, the big-endian u32 length
// and the payload.
func EncodeRecord(recordType byte, payload []byte) []byte {
	buffer := make([]byte, RecordHeaderBytes+len(payload))
	buffer[0] = recordType
	binary.BigEndian.PutUint32(buffer[1:], uint32(len(payload)))
	copy(buffer[RecordHeaderBytes:], payload)
	return buffer
}

// WriteRecord writes one record in one call. It returns ErrRecordTooLarge
// for a payload past RecordBytesMax.
func WriteRecord(w io.Writer, recordType byte, payload []byte) error {
	if len(payload) > RecordBytesMax {
		return fmt.Errorf("%w: %d bytes", ErrRecordTooLarge, len(payload))
	}
	_, err := w.Write(EncodeRecord(recordType, payload))
	return err
}

// OpenRecord is the open record of a stream of kind with args, the open's
// own fields.
func OpenRecord(kind string, args map[string]any) []byte {
	fields := make(map[string]any, len(args)+1)
	for key, value := range args {
		fields[key] = value
	}
	fields["kind"] = kind
	payload, err := json.Marshal(fields)
	if err != nil {
		panic(err)
	}
	return EncodeRecord(RecordOpen, payload)
}

// CloseRecord is a close record: a refusal when code is set, a result when
// it is empty.
func CloseRecord(code string, params map[string]any) []byte {
	fields := map[string]any{"params": params}
	if params == nil {
		fields["params"] = map[string]any{}
	}
	if code != "" {
		fields["code"] = code
	}
	payload, err := json.Marshal(fields)
	if err != nil {
		panic(err)
	}
	return EncodeRecord(RecordClose, payload)
}

// AcceptRecord is the one accept record.
func AcceptRecord() []byte {
	return EncodeRecord(RecordAccept, nil)
}

// OpenKind reads the kind of an open record's payload. It returns an error
// for a payload that is not a JSON object with a kind.
func OpenKind(payload []byte) (string, error) {
	var open struct {
		Kind string `json:"kind"`
	}
	if err := json.Unmarshal(payload, &open); err != nil {
		return "", fmt.Errorf("open record: %w", err)
	}
	if open.Kind == "" {
		return "", fmt.Errorf("open record: no kind")
	}
	return open.Kind, nil
}

// ParseClose reads a close record's payload as a refusal; a close with no
// code has an empty Code.
func ParseClose(payload []byte) (*Refusal, error) {
	var refusal Refusal
	if err := json.Unmarshal(payload, &refusal); err != nil {
		return nil, fmt.Errorf("close record: %w", err)
	}
	if refusal.Params == nil {
		refusal.Params = map[string]any{}
	}
	return &refusal, nil
}

// ReadAnswer reads the record that answers an open: nil for an accept, the
// refusal for a refusing close, and ErrRecordUnexpected for any other type.
func ReadAnswer(r *bufio.Reader) (*Refusal, error) {
	record, err := ReadRecord(r)
	if err != nil {
		return nil, err
	}
	switch record.Type {
	case RecordAccept:
		return nil, nil
	case RecordClose:
		refusal, err := ParseClose(record.Payload)
		if err != nil {
			return nil, err
		}
		return refusal, nil
	default:
		return nil, fmt.Errorf("%w: type %d before an accept", ErrRecordUnexpected, record.Type)
	}
}

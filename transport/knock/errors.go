package knock

import "errors"

var (
	// ErrKnockMalformed is a knock whose version, length or macs do not fit.
	ErrKnockMalformed = errors.New("knock malformed")
	// ErrMac1Invalid is a knock whose mac1 does not verify under the hub's key.
	ErrMac1Invalid = errors.New("knock mac1 invalid")
	// ErrCookieReplyMalformed is a cookie reply that does not open.
	ErrCookieReplyMalformed = errors.New("cookie reply malformed")
	// ErrNotCookieReply is an answer whose first byte is not a cookie reply's.
	ErrNotCookieReply = errors.New("not a cookie reply")
)

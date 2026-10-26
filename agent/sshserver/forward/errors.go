package forward

import "errors"

// ErrDestinationRefused is returned for a forward whose destination is not
// on loopback, or whose request cannot be read.
var ErrDestinationRefused = errors.New("destination refused")

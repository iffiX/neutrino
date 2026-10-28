package knock

import (
	cryptorand "crypto/rand"
	"math/rand/v2"
)

// Padding returns 0 to KnockPaddingBytesMax random bytes, the count drawn
// for each call.
func Padding() []byte {
	padding := make([]byte, rand.IntN(KnockPaddingBytesMax+1))
	_, _ = cryptorand.Read(padding)
	return padding
}

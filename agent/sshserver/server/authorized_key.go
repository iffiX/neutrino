package server

import (
	"bytes"
	"fmt"
	"os"

	"golang.org/x/crypto/ssh"
)

// keyAuthenticator admits the one authorized key and nothing else.
type keyAuthenticator struct {
	authorized []byte
}

// newKeyAuthenticator returns the check for one authorized key.
func newKeyAuthenticator(key ssh.PublicKey) *keyAuthenticator {
	return &keyAuthenticator{authorized: key.Marshal()}
}

// check is the server's public key callback. It returns the key's
// fingerprint in the permissions for the authorized key, and
// ErrKeyNotAuthorized for any other key, a certificate among them.
func (a *keyAuthenticator) check(_ ssh.ConnMetadata, key ssh.PublicKey) (*ssh.Permissions, error) {
	if !bytes.Equal(key.Marshal(), a.authorized) {
		return nil, ErrKeyNotAuthorized
	}
	return &ssh.Permissions{
		Extensions: map[string]string{"fingerprint": ssh.FingerprintSHA256(key)},
	}, nil
}

// ReadAuthorizedKey reads the one public key in the authorized_keys form
// file at path; a line the file holds after the first key is not read. It
// returns ErrAuthorizedKeyMissing for a file with no key, and the file's
// error when it cannot be read.
func ReadAuthorizedKey(path string) (ssh.PublicKey, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read authorized key: %w", err)
	}
	if len(bytes.TrimSpace(data)) == 0 {
		return nil, fmt.Errorf("%s: %w", path, ErrAuthorizedKeyMissing)
	}
	key, _, _, _, err := ssh.ParseAuthorizedKey(data)
	if err != nil {
		return nil, fmt.Errorf("%s: %w: %v", path, ErrAuthorizedKeyMissing, err)
	}
	return key, nil
}

package server

import (
	"errors"
	"os"
	"path/filepath"
	"testing"

	"golang.org/x/crypto/ssh"
)

func TestReadAuthorizedKeyReadsTheOneKey(t *testing.T) {
	key := newSigner(t).PublicKey()
	directory := t.TempDir()
	cases := []struct {
		name    string
		content string
		want    error
	}{
		{"one key", PublicKeyLine(key) + " lab@machine\n", nil},
		{"an empty file", "", ErrAuthorizedKeyMissing},
		{"blank lines", "\n  \n", ErrAuthorizedKeyMissing},
		{"no key", "ssh-ed25519 not-base64\n", ErrAuthorizedKeyMissing},
	}
	for index, test := range cases {
		t.Run(test.name, func(t *testing.T) {
			path := filepath.Join(directory, string(rune('a'+index)))
			os.WriteFile(path, []byte(test.content), 0o600)
			read, err := ReadAuthorizedKey(path)
			if test.want != nil {
				if !errors.Is(err, test.want) {
					t.Fatalf("got %v, want %v", err, test.want)
				}
				return
			}
			if err != nil || PublicKeyLine(read) != PublicKeyLine(key) {
				t.Fatalf("read %v, %v", read, err)
			}
		})
	}
	if _, err := ReadAuthorizedKey(filepath.Join(directory, "missing")); !errors.Is(err, os.ErrNotExist) {
		t.Fatalf("missing file: got %v, want os.ErrNotExist", err)
	}
}

func TestKeyAuthenticatorAdmitsTheAuthorizedKeyAlone(t *testing.T) {
	authorized := newSigner(t).PublicKey()
	check := newKeyAuthenticator(authorized).check
	cases := []struct {
		name       string
		key        ssh.PublicKey
		isAdmitted bool
	}{
		{"the authorized key", authorized, true},
		{"another key", newSigner(t).PublicKey(), false},
	}
	for _, test := range cases {
		t.Run(test.name, func(t *testing.T) {
			permissions, err := check(nil, test.key)
			if test.isAdmitted != (err == nil) {
				t.Fatalf("admitted %v, want %v", err == nil, test.isAdmitted)
			}
			if test.isAdmitted && permissions.Extensions["fingerprint"] != ssh.FingerprintSHA256(authorized) {
				t.Errorf("fingerprint %q", permissions.Extensions["fingerprint"])
			}
		})
	}
}

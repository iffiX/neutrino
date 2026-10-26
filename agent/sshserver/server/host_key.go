package server

import (
	"crypto/ed25519"
	"crypto/rand"
	"encoding/pem"
	"fmt"
	"os"
	"strings"

	"golang.org/x/crypto/ssh"
)

// MakeHostKey writes a new Ed25519 host key to path in OpenSSH form, mode
// 0600, and returns its public half as one authorized_keys line. It never
// replaces a file: it returns an error wrapping os.ErrExist when path is
// already there.
func MakeHostKey(path string) (string, error) {
	_, private, err := ed25519.GenerateKey(rand.Reader)
	if err != nil {
		return "", fmt.Errorf("generate host key: %w", err)
	}
	block, err := ssh.MarshalPrivateKey(private, "")
	if err != nil {
		return "", fmt.Errorf("encode host key: %w", err)
	}
	signer, err := ssh.NewSignerFromKey(private)
	if err != nil {
		return "", fmt.Errorf("sign with host key: %w", err)
	}
	file, err := os.OpenFile(path, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
	if err != nil {
		return "", fmt.Errorf("create %s: %w", path, err)
	}
	if _, err := file.Write(pem.EncodeToMemory(block)); err != nil {
		file.Close()
		return "", fmt.Errorf("write %s: %w", path, err)
	}
	if err := file.Sync(); err != nil {
		file.Close()
		return "", fmt.Errorf("sync %s: %w", path, err)
	}
	if err := file.Close(); err != nil {
		return "", fmt.Errorf("close %s: %w", path, err)
	}
	return PublicKeyLine(signer.PublicKey()), nil
}

// ReadHostKey reads the private host key at path, in OpenSSH or PEM form
// without a passphrase. It returns the file's error, or the parser's for a
// file that holds no usable key.
func ReadHostKey(path string) (ssh.Signer, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read host key: %w", err)
	}
	signer, err := ssh.ParsePrivateKey(data)
	if err != nil {
		return nil, fmt.Errorf("parse host key %s: %w", path, err)
	}
	return signer, nil
}

// PublicKeyLine returns a public key as one authorized_keys line without a
// comment or a line end, such as "ssh-ed25519 AAAA...".
func PublicKeyLine(key ssh.PublicKey) string {
	return strings.TrimSpace(string(ssh.MarshalAuthorizedKey(key)))
}

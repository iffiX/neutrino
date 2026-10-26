package relay

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"github.com/flynn/noise"

	"github.com/iffiX/neutrino/transport/handshake"
)

// LoadOrCreateKey reads the hub's static key from dir, making a new pair when
// the private half is missing, and writes the public half beside it. The
// directory is made with mode 0700 when it does not exist. It returns an
// error when a file cannot be read or written, or holds something that is
// not a key.
func LoadOrCreateKey(dir string) (noise.DHKey, error) {
	if err := os.MkdirAll(dir, RelayKeyDirMode); err != nil {
		return noise.DHKey{}, fmt.Errorf("key directory: %w", err)
	}
	privatePath := filepath.Join(dir, RelayStaticKeyFile)
	var key noise.DHKey
	text, err := os.ReadFile(privatePath)
	switch {
	case err == nil:
		key, err = handshake.KeyFromPrivate(strings.TrimSpace(string(text)))
		if err != nil {
			return noise.DHKey{}, fmt.Errorf("%s: %w", privatePath, err)
		}
	case errors.Is(err, os.ErrNotExist):
		key, err = handshake.GenerateKey()
		if err != nil {
			return noise.DHKey{}, err
		}
		if err := writeFile(privatePath, handshake.EncodeKey(key.Private)+"\n", RelayStaticKeyMode); err != nil {
			return noise.DHKey{}, err
		}
	default:
		return noise.DHKey{}, fmt.Errorf("%s: %w", privatePath, err)
	}
	publicPath := filepath.Join(dir, RelayPublicKeyFile)
	if err := writeFile(publicPath, handshake.EncodeKey(key.Public)+"\n", RelayPublicKeyMode); err != nil {
		return noise.DHKey{}, err
	}
	return key, nil
}

// writeFile writes a file whole with mode, replacing it atomically.
func writeFile(path, text string, mode os.FileMode) error {
	temporary := path + ".tmp"
	if err := os.WriteFile(temporary, []byte(text), mode); err != nil {
		return fmt.Errorf("write %s: %w", path, err)
	}
	if err := os.Chmod(temporary, mode); err != nil {
		return fmt.Errorf("chmod %s: %w", path, err)
	}
	if err := os.Rename(temporary, path); err != nil {
		return fmt.Errorf("rename %s: %w", path, err)
	}
	return nil
}

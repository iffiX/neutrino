package server

import (
	"errors"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestMakeHostKeyOwnerAlone(t *testing.T) {
	path := filepath.Join(t.TempDir(), "host_key")
	line, err := MakeHostKey(path)
	if err != nil {
		t.Fatal(err)
	}
	info, err := os.Stat(path)
	if err != nil {
		t.Fatal(err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Errorf("mode %v, want 0600", info.Mode().Perm())
	}
	data, _ := os.ReadFile(path)
	if !strings.HasPrefix(string(data), "-----BEGIN OPENSSH PRIVATE KEY-----") {
		t.Errorf("not in OpenSSH form: %q", data[:40])
	}
	signer, err := ReadHostKey(path)
	if err != nil {
		t.Fatal(err)
	}
	if !strings.HasPrefix(line, "ssh-ed25519 ") || PublicKeyLine(signer.PublicKey()) != line {
		t.Errorf("printed %q, read back %q", line, PublicKeyLine(signer.PublicKey()))
	}
}

func TestMakeHostKeyNeverReplacesAFile(t *testing.T) {
	path := filepath.Join(t.TempDir(), "host_key")
	if err := os.WriteFile(path, []byte("kept"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := MakeHostKey(path); !errors.Is(err, os.ErrExist) {
		t.Fatalf("got %v, want os.ErrExist", err)
	}
	if data, _ := os.ReadFile(path); string(data) != "kept" {
		t.Fatalf("file changed to %q", data)
	}
}

func TestReadHostKeyRefusesWhatIsNotAKey(t *testing.T) {
	directory := t.TempDir()
	path := filepath.Join(directory, "host_key")
	os.WriteFile(path, []byte("not a key"), 0o600)
	cases := []struct {
		name string
		path string
	}{
		{"a file that holds no key", path},
		{"a missing file", filepath.Join(directory, "missing")},
	}
	for _, test := range cases {
		t.Run(test.name, func(t *testing.T) {
			if _, err := ReadHostKey(test.path); err == nil {
				t.Fatal("read")
			}
		})
	}
}

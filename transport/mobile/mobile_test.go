package mobile

import (
	"bufio"
	"encoding/json"
	"net"
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"
)

const secret = "0000000000000000000000000000000000000000000000000000000000000009"

func TestStartAndStop(t *testing.T) {
	dir, err := os.MkdirTemp("", "nm")
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(dir)
	path, err := Start(dir, secret)
	if err != nil {
		t.Fatal(err)
	}
	if path != filepath.Join(dir, MobileSocketName) {
		t.Fatalf("path %s", path)
	}
	if _, err := Start(dir, secret); err != ErrAlreadyRunning {
		t.Fatalf("second start: %v", err)
	}
	conn, err := net.DialTimeout("unix", path, time.Second)
	if err != nil {
		t.Fatal(err)
	}
	_, _ = conn.Write([]byte(`{"secret":"` + secret + `","op":"control"}` + "\n"))
	_, _ = conn.Write([]byte(`{"id":"1","command":"round","binding":"none"}` + "\n"))
	line, err := bufio.NewReader(conn).ReadBytes('\n')
	if err != nil {
		t.Fatal(err)
	}
	var answer map[string]any
	_ = json.Unmarshal(line, &answer)
	if answer["id"] != "1" || answer["code"] != "binding_unknown" {
		t.Fatalf("answer %v", answer)
	}
	conn.Close()
	Stop()
	if IsRunning() {
		t.Fatal("still running after stop")
	}
	if _, err := net.DialTimeout("unix", path, time.Second); err == nil {
		t.Fatal("the socket still answers after stop")
	}
	Stop()
}

func TestLongDirectoryFallsBack(t *testing.T) {
	long := filepath.Join(os.TempDir(), strings.Repeat("d", 120))
	path, err := Start(long, secret)
	if err != nil {
		t.Fatal(err)
	}
	defer Stop()
	defer os.RemoveAll(filepath.Dir(path))
	if strings.HasPrefix(path, long) || len(path) > MobileSocketPathMax {
		t.Fatalf("path %s", path)
	}
	info, err := os.Stat(filepath.Dir(path))
	if err != nil || (runtime.GOOS != "windows" && info.Mode().Perm() != MobileFallbackDirMode) {
		t.Fatalf("fallback directory %v %v", info, err)
	}
	if _, err := Start(long, "short"); err != ErrAlreadyRunning {
		t.Fatalf("%v", err)
	}
}

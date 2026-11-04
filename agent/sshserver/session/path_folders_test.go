package session

import (
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
)

func TestReadPathFoldersTakesEachLineThatNamesAFolder(t *testing.T) {
	path := filepath.Join(t.TempDir(), "path_folders")
	if err := os.WriteFile(path, []byte("/a/bin\r\n\n  /b/bin \n"), 0o644); err != nil {
		t.Fatal(err)
	}
	if got, want := readPathFolders(path), []string{"/a/bin", "/b/bin"}; !reflect.DeepEqual(got, want) {
		t.Fatalf("got %q, want %q", got, want)
	}
	for _, missing := range []string{"", filepath.Join(t.TempDir(), "missing"), t.TempDir()} {
		if got := readPathFolders(missing); len(got) != 0 {
			t.Fatalf("%q gave %q", missing, got)
		}
	}
}

func TestWithPathFoldersPutsEachFolderFirstOnce(t *testing.T) {
	separator := string(os.PathListSeparator)
	joined := func(parts ...string) string { return strings.Join(parts, separator) }
	environment := []string{"HOME=/h", "PATH=" + joined("/usr/bin", "/b/bin", "/bin")}

	got := withPathFolders(environment, []string{"/a/bin", "/b/bin", "/a/bin"})

	if value, _ := lookupVariable(got, "PATH"); value != joined("/a/bin", "/b/bin", "/usr/bin", "/bin") {
		t.Fatalf("PATH %q", value)
	}
	if value, _ := lookupVariable(got, "HOME"); value != "/h" {
		t.Fatalf("HOME %q", value)
	}
	if got := withPathFolders(environment, nil); !reflect.DeepEqual(got, environment) {
		t.Fatalf("no folders changed the environment to %q", got)
	}
	if value, _ := lookupVariable(withPathFolders([]string{"HOME=/h"}, []string{"/a/bin"}), "PATH"); value != "/a/bin" {
		t.Fatalf("PATH with none before %q", value)
	}
}

package session

import (
	"io"
	"os"
	"path/filepath"
	"strings"
)

// readPathFolders returns the folders the file at path names, one per line,
// blank lines left out. A path that is empty, missing or unreadable names
// none.
func readPathFolders(path string) []string {
	if path == "" {
		return nil
	}
	file, err := openPathFolders(path)
	if err != nil {
		return nil
	}
	defer file.Close()
	data, err := io.ReadAll(io.LimitReader(file, SessionPathFoldersLimit))
	if err != nil {
		return nil
	}
	folders := []string{}
	for _, line := range strings.Split(string(data), "\n") {
		if folder := strings.TrimSpace(line); folder != "" {
			folders = append(folders, folder)
		}
	}
	return folders
}

// withPathFolders returns environment with its PATH starting with folders,
// each once, then the PATH it held without them, under the name it held.
func withPathFolders(environment []string, folders []string) []string {
	if len(folders) == 0 {
		return environment
	}
	name, held := "PATH", ""
	for _, entry := range environment {
		if isVariable(entry, "PATH") {
			name, held, _ = strings.Cut(entry, "=")
		}
	}
	isFirst := map[string]bool{}
	parts := []string{}
	for _, folder := range folders {
		if !isFirst[folder] {
			isFirst[folder] = true
			parts = append(parts, folder)
		}
	}
	for _, part := range filepath.SplitList(held) {
		if !isFirst[part] {
			parts = append(parts, part)
		}
	}
	return withVariable(environment, name, strings.Join(parts, string(os.PathListSeparator)))
}

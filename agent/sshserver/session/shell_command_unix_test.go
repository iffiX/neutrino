//go:build linux || darwin

package session

import (
	"reflect"
	"testing"
)

func TestShellCommandStartsALoginShellOrRunsTheCommand(t *testing.T) {
	account := Account{Shell: "/bin/bash", Home: t.TempDir()}
	cases := []struct {
		name    string
		command string
		isLogin bool
		want    []string
	}{
		{"a login shell", "", true, []string{"-bash"}},
		{"a command", "echo hi", false, []string{"bash", "-c", "echo hi"}},
	}
	for _, test := range cases {
		t.Run(test.name, func(t *testing.T) {
			cmd := shellCommand(account, test.command, test.isLogin)
			if cmd.Path != "/bin/bash" || !reflect.DeepEqual(cmd.Args, test.want) || cmd.Dir != account.Home {
				t.Fatalf("path %q args %q dir %q", cmd.Path, cmd.Args, cmd.Dir)
			}
		})
	}
}

func TestAMissingHomeStartsAtTheRoot(t *testing.T) {
	cmd := shellCommand(Account{Shell: "/bin/sh", Home: "/nonexistent/home"}, "", true)
	if cmd.Dir != "/" {
		t.Fatalf("dir %q", cmd.Dir)
	}
}

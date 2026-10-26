package session

import "testing"

func TestCurrentAccountDropsTheServersOwnVariables(t *testing.T) {
	t.Setenv("NEUTRINO_SSH_SERVER_PORT", "22000")
	t.Setenv("LANG", "C.UTF-8")
	account := CurrentAccount("/bin/sh")
	if _, ok := lookupVariable(account.Environment, "NEUTRINO_SSH_SERVER_PORT"); ok {
		t.Error("the server's own variable is passed on")
	}
	if value, _ := lookupVariable(account.Environment, "SHELL"); value != "/bin/sh" {
		t.Errorf("SHELL is %q", value)
	}
	if value, _ := lookupVariable(account.Environment, "LANG"); value != "C.UTF-8" {
		t.Errorf("LANG is %q", value)
	}
	if account.Shell != "/bin/sh" || account.Home == "" {
		t.Errorf("account %+v", account)
	}
}

func TestCurrentAccountFillsWhatTheServiceLeftOut(t *testing.T) {
	t.Setenv("PATH", "")
	account := CurrentAccount("/bin/sh")
	for _, name := range []string{"HOME", "USER", "LOGNAME"} {
		if value, ok := lookupVariable(account.Environment, name); !ok || value == "" {
			t.Errorf("%s missing", name)
		}
	}
}

package session

import (
	"net"
	"reflect"
	"testing"
)

func TestOnlyLocaleVariablesAreAccepted(t *testing.T) {
	cases := []struct {
		name       string
		isAccepted bool
	}{
		{"LANG", true},
		{"LANGUAGE", true},
		{"LC_ALL", true},
		{"LC_CTYPE", true},
		{"PATH", false},
		{"LD_PRELOAD", false},
		{"HOME", false},
		{"", false},
		{"LC_A=B", false},
	}
	for _, test := range cases {
		t.Run(test.name, func(t *testing.T) {
			if isAcceptedVariable(test.name) != test.isAccepted {
				t.Fatalf("accepted %v, want %v", !test.isAccepted, test.isAccepted)
			}
		})
	}
}

func TestWithVariableReplacesWhatWasThere(t *testing.T) {
	got := withVariables([]string{"A=1", "B=2"}, []string{"A=3", "C=4"})
	want := []string{"B=2", "A=3", "C=4"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
	if value, ok := lookupVariable(got, "A"); !ok || value != "3" {
		t.Fatalf("A is %q, %v", value, ok)
	}
}

func TestPeerEnvironmentIsOpenSSHs(t *testing.T) {
	remote := &net.TCPAddr{IP: net.ParseIP("127.0.0.1"), Port: 40000}
	local := &net.TCPAddr{IP: net.ParseIP("127.0.0.1"), Port: 22000}
	want := []string{
		"SSH_CLIENT=127.0.0.1 40000 22000",
		"SSH_CONNECTION=127.0.0.1 40000 127.0.0.1 22000",
	}
	if got := PeerEnvironment(remote, local); !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
}

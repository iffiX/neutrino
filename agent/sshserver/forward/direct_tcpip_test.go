package forward

import (
	"reflect"
	"testing"
)

func TestOnlyLoopbackDestinationsAreDialed(t *testing.T) {
	cases := []struct {
		host string
		want []string
	}{
		{"127.0.0.1", []string{"127.0.0.1"}},
		{"::1", []string{"::1"}},
		{"localhost", []string{"127.0.0.1", "::1"}},
		{"LocalHost", []string{"127.0.0.1", "::1"}},
		{"127.0.0.2", nil},
		{"0.0.0.0", nil},
		{"192.168.1.1", nil},
		{"localhost.example.com", nil},
		{"[::1]", nil},
		{"", nil},
	}
	for _, test := range cases {
		t.Run(test.host, func(t *testing.T) {
			if got := loopbackHosts(test.host); !reflect.DeepEqual(got, test.want) {
				t.Fatalf("got %v, want %v", got, test.want)
			}
		})
	}
}

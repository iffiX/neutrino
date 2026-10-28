module github.com/iffiX/neutrino/transport

go 1.27.3

require (
	github.com/flynn/noise v1.1.0
	github.com/libp2p/go-yamux/v4 v4.0.2
	github.com/pion/datachannel v1.6.3
	github.com/pion/dtls/v3 v3.1.15
	github.com/pion/logging v0.2.4
	github.com/pion/sctp v1.12.0
	github.com/pion/stun/v3 v3.1.7
	golang.org/x/crypto v0.58.0
)

require (
	github.com/libp2p/go-buffer-pool v0.0.2 // indirect
	github.com/pion/randutil v0.1.0 // indirect
	github.com/pion/transport/v4 v4.1.0 // indirect
	github.com/pion/transport/v5 v5.1.1 // indirect
	github.com/wlynxg/anet v0.0.5 // indirect
	golang.org/x/mobile v0.0.0-20260816165457-f98cc9b3c733 // indirect
	golang.org/x/mod v0.42.0 // indirect
	golang.org/x/sync v0.24.0 // indirect
	golang.org/x/sys v0.49.0 // indirect
	golang.org/x/tools v0.52.0 // indirect
)

tool (
	golang.org/x/mobile/cmd/gobind
	golang.org/x/mobile/cmd/gomobile
)

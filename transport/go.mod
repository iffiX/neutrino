module github.com/iffiX/neutrino/transport

go 1.27.3

require (
	github.com/flynn/noise v1.1.0
	github.com/libp2p/go-yamux/v4 v4.0.2
	golang.org/x/crypto v0.58.0
)

require (
	github.com/libp2p/go-buffer-pool v0.0.2 // indirect
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

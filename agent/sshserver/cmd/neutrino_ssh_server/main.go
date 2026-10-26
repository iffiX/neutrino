package main

import (
	"context"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"syscall"

	"github.com/iffiX/neutrino/agent/sshserver/server"
)

// version is stamped by the build with -ldflags "-X main.version=...".
var version = "dev"

func main() {
	listen := flag.String("listen", "", "the loopback address and port to listen on, 127.0.0.1:<port>")
	hostKey := flag.String("host-key", "", "the host key file, OpenSSH form")
	authorizedKey := flag.String("authorized-key", "", "the file holding the one public key admitted")
	shell := flag.String("shell", "", "the shell a session starts, an absolute path")
	makeHostKey := flag.String("make-host-key", "", "write a new Ed25519 host key to this file, print its public key and exit")
	isVersion := flag.Bool("version", false, "print the version and exit")
	flag.Parse()

	if *isVersion {
		fmt.Println(version)
		return
	}
	if *makeHostKey != "" {
		publicKey, err := server.MakeHostKey(*makeHostKey)
		if err != nil {
			writeEvent("host_key_failed", "error", err.Error())
			os.Exit(1)
		}
		fmt.Println(publicKey)
		return
	}
	if *listen == "" || *hostKey == "" || *authorizedKey == "" || *shell == "" {
		flag.Usage()
		os.Exit(2)
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	if err := server.Run(ctx, *listen, *hostKey, *authorizedKey, *shell, writeEvent); err != nil {
		writeEvent("exited", "error", err.Error())
		os.Exit(1)
	}
}

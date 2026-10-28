// Command neutrino_transport holds the channel for the hub, the agent and
// the desktop client, one mode each, and probes an address for a hub.
//
//	neutrino_transport hub --config <transport.json> --key-dir <dir> [--secret-file <path>]
//	neutrino_transport agent --listen <socket or pipe>
//	neutrino_transport client --listen <socket or pipe>
//	neutrino_transport probe --key <public-key-hex> <address>
//	neutrino_transport --version
//
// The agent and the client read the local channel's secret as the first
// line of standard input and exit when standard input ends; the hub reads it
// from --secret-file, or from standard input without one.
package main

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"os"
	"strings"
	"time"

	"github.com/iffiX/neutrino/transport/control"
	"github.com/iffiX/neutrino/transport/gate"
	"github.com/iffiX/neutrino/transport/handshake"
	"github.com/iffiX/neutrino/transport/knock"
	"github.com/iffiX/neutrino/transport/relay"
	"github.com/iffiX/neutrino/transport/session"
)

// version is stamped by the build with -ldflags "-X main.version=...".
var version = "dev"

// transportFile is generated/transport.json, what the hub's Python renders
// for the transport to open.
type transportFile struct {
	ListenPort    int                 `json:"listen_port"`
	FrpListeners  []relay.FrpListener `json:"frp_listeners"`
	ControlSocket string              `json:"control_socket"`
}

func main() {
	os.Exit(run(os.Args[1:]))
}

func run(args []string) int {
	if len(args) == 0 {
		usage()
		return 2
	}
	switch args[0] {
	case "--version", "version":
		fmt.Println(version)
		return 0
	case "hub":
		return runHub(args[1:])
	case "agent":
		return runPeer(control.RoleAgent, args[1:])
	case "client":
		return runPeer(control.RoleClient, args[1:])
	case "probe":
		return runProbe(args[1:])
	}
	usage()
	return 2
}

func usage() {
	fmt.Fprintln(os.Stderr, "usage: neutrino_transport hub|agent|client|probe [flags]")
}

// logLine writes one event line: a verb and key=value pairs.
func logLine(verb string, fields ...string) {
	var builder strings.Builder
	builder.WriteString(time.Now().UTC().Format(time.RFC3339))
	builder.WriteByte(' ')
	builder.WriteString(verb)
	for i := 0; i+1 < len(fields); i += 2 {
		builder.WriteByte(' ')
		builder.WriteString(fields[i])
		builder.WriteByte('=')
		value := fields[i+1]
		if strings.ContainsAny(value, " \t\"") {
			value = fmt.Sprintf("%q", value)
		}
		builder.WriteString(value)
	}
	fmt.Fprintln(os.Stderr, builder.String())
}

// readSecret reads the secret from standard input's first line.
func readSecret(reader *bufio.Reader) (string, error) {
	line, err := reader.ReadString('\n')
	if err != nil && line == "" {
		return "", fmt.Errorf("read secret: %w", err)
	}
	secret := strings.TrimSpace(line)
	if len(secret) != control.ControlSecretChars {
		return "", fmt.Errorf("secret: %d characters, want %d", len(secret), control.ControlSecretChars)
	}
	return secret, nil
}

// watchStdin exits the process once standard input ends: the parent is gone.
func watchStdin(reader *bufio.Reader, stop func()) {
	_, _ = io.Copy(io.Discard, reader)
	logLine("stdin_closed")
	stop()
}

func runHub(args []string) int {
	flags := flag.NewFlagSet("hub", flag.ContinueOnError)
	configPath := flags.String("config", "", "the transport.json the hub rendered")
	keyDir := flags.String("key-dir", "", "the directory of the hub's static key")
	secretFile := flags.String("secret-file", "", "the control secret's file; standard input when absent")
	if err := flags.Parse(args); err != nil {
		return 2
	}
	if *configPath == "" || *keyDir == "" {
		fmt.Fprintln(os.Stderr, "hub: --config and --key-dir are required")
		return 2
	}
	data, err := os.ReadFile(*configPath)
	if err != nil {
		logLine("config_unreadable", "path", *configPath, "error", err.Error())
		return 1
	}
	var file transportFile
	if err := json.Unmarshal(data, &file); err != nil {
		logLine("config_invalid", "path", *configPath, "error", err.Error())
		return 1
	}
	if file.ControlSocket == "" || file.ListenPort == 0 {
		logLine("config_invalid", "path", *configPath, "error", "control_socket and listen_port are required")
		return 1
	}
	var secret string
	stdin := bufio.NewReader(os.Stdin)
	if *secretFile != "" {
		text, err := os.ReadFile(*secretFile)
		if err != nil {
			logLine("secret_unreadable", "path", *secretFile, "error", err.Error())
			return 1
		}
		secret = strings.TrimSpace(string(text))
		if len(secret) != control.ControlSecretChars {
			logLine("secret_invalid", "path", *secretFile)
			return 1
		}
	} else {
		secret, err = readSecret(stdin)
		if err != nil {
			logLine("secret_unreadable", "error", err.Error())
			return 1
		}
	}
	key, err := relay.LoadOrCreateKey(*keyDir)
	if err != nil {
		logLine("key_unreadable", "dir", *keyDir, "error", err.Error())
		return 1
	}
	certificate, err := gate.LoadOrCreateCertificate(*keyDir)
	if err != nil {
		logLine("certificate_unreadable", "dir", *keyDir, "error", err.Error())
		return 1
	}
	listener, err := control.Listen(file.ControlSocket, false)
	if err != nil {
		logLine("control_listen_failed", "path", file.ControlSocket, "error", err.Error())
		return 1
	}
	hubControl := control.NewHubControl(listener, secret, *keyDir, logLine)
	hub, err := relay.NewHub(relay.HubConfig{
		Key: key, ListenPort: file.ListenPort, FrpListeners: file.FrpListeners,
		Certificate: &certificate, Log: logLine,
	}, hubControl)
	if err != nil {
		logLine("hub_failed", "error", err.Error())
		return 1
	}
	hubControl.SetHub(hub)
	if err := hub.Listen(); err != nil {
		logLine("listen_failed", "error", err.Error())
		return 1
	}
	logLine("started", "mode", "hub", "version", version, "public_key", handshake.EncodeKey(hub.PublicKey()), "dtls_fingerprint", hub.Fingerprint(), "control", file.ControlSocket)
	done := make(chan struct{})
	if *secretFile == "" {
		go watchStdin(stdin, func() { close(done) })
	}
	go func() {
		hubControl.Serve()
		select {
		case <-done:
		default:
			close(done)
		}
	}()
	<-done
	hub.Close()
	hubControl.Close()
	return 0
}

func runPeer(role string, args []string) int {
	flags := flag.NewFlagSet(role, flag.ContinueOnError)
	listen := flags.String("listen", "", "the local channel's socket or pipe")
	if err := flags.Parse(args); err != nil {
		return 2
	}
	if *listen == "" {
		fmt.Fprintf(os.Stderr, "%s: --listen is required\n", role)
		return 2
	}
	stdin := bufio.NewReader(os.Stdin)
	secret, err := readSecret(stdin)
	if err != nil {
		logLine("secret_unreadable", "error", err.Error())
		return 1
	}
	listener, err := control.Listen(*listen, role == control.RoleClient)
	if err != nil {
		logLine("control_listen_failed", "path", *listen, "error", err.Error())
		return 1
	}
	var serve func()
	var stop func()
	if role == control.RoleAgent {
		agent := control.NewAgentControl(listener, secret, session.DefaultTimings, logLine)
		serve, stop = agent.Serve, agent.Close
	} else {
		client := control.NewClientControl(listener, secret, session.DefaultTimings, logLine)
		serve, stop = client.Serve, client.Close
	}
	logLine("started", "mode", role, "version", version, "control", *listen)
	done := make(chan struct{})
	go watchStdin(stdin, func() { close(done) })
	go func() {
		serve()
		select {
		case <-done:
		default:
			close(done)
		}
	}()
	<-done
	stop()
	if !control.IsPipePath(*listen) {
		_ = os.Remove(*listen)
	}
	return 0
}

// runProbe knocks at an address as a join and exits 0 when message 2 opens
// under the key given.
func runProbe(args []string) int {
	flags := flag.NewFlagSet("probe", flag.ContinueOnError)
	keyHex := flags.String("key", "", "the hub's static public key, 64 hex characters")
	if err := flags.Parse(args); err != nil {
		return 2
	}
	if *keyHex == "" || flags.NArg() != 1 {
		fmt.Fprintln(os.Stderr, "usage: neutrino_transport probe --key <public-key-hex> <address>")
		return 2
	}
	hubPublic, err := handshake.DecodeKey(*keyHex)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 2
	}
	static, err := handshake.GenerateKey()
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		return 1
	}
	ctx, cancel := context.WithTimeout(context.Background(), knock.HandshakeTimeout)
	defer cancel()
	result, err := session.Dial(ctx, flags.Arg(0), session.DialOptions{
		Static: static, HubPublic: hubPublic, Psk: handshake.ZeroPsk,
		Protocol: knock.PROTOCOL, Role: knock.KnockRoleClient, IsJoin: true,
		Timeout: knock.HandshakeTimeout,
	})
	if err != nil {
		if errors.Is(err, handshake.ErrHubUntrusted) {
			fmt.Fprintln(os.Stderr, "hub_untrusted")
		} else {
			fmt.Fprintln(os.Stderr, err)
		}
		return 1
	}
	result.Conn.Close()
	return 0
}

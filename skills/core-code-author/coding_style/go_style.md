# Go style

The transport (`transport/`) is one Go module shared by the hub, the agent
and the clients: the knock, the Noise handshake, the yamux sessions, the
relay between streams, and the local control channel the Python side talks
to. The hub, the agent and the desktop client carry it as a binary; the
Android and iOS apps embed it as a gomobile library. This file is its
language surface. The shared intent is set by
[naming_style.md](naming_style.md), [comment_style.md](comment_style.md) and
[exception_style.md](exception_style.md), and applies here as it does to
Python.

## Example

```go
// BAD: file named after nothing, a noun bool, a panic on a wire fault, a refusal as a string
// util.go
type Manager struct{ connected bool }

func (m *Manager) Open(id string) *Stream {
	s, err := m.session.Open()
	if err != nil {
		panic(err)
	}
	if reply.Code != "" {
		return nil
	}
	return s
}

// GOOD: file named after its one concept, is bool, the error returned, a refusal as a typed error
// relay_session.go
type RelaySession struct {
	isAdmitted bool
	session    *yamux.Session
}

// OpenEntry opens one stream to the entry an admitted peer names.
// It returns the stream, or a *Refusal when the hub's table does not
// allow the entry, or the session's error when the connection is gone.
func (r *RelaySession) OpenEntry(ctx context.Context, entry EntryID) (net.Conn, error) {
	if !r.isAdmitted {
		return nil, &Refusal{Code: "binding_unknown"}
	}
	stream, err := r.session.OpenStream()
	if err != nil {
		return nil, fmt.Errorf("open stream to %s: %w", entry, err)
	}
	return stream, nil
}
```

## Formatting and linting

- `gofmt` is the formatter and `go vet` the first linter; both must pass on
  every change, the same gate as black on Python. `staticcheck` runs beside
  them in CI with no findings.
- The build is warning-free and `go test -race ./...` passes. Do not silence
  a finding with a `//nolint` comment to hide a real problem.

## Module and dependencies

- `transport/go.mod` is the transport's module, named
  `github.com/iffiX/neutrino/transport`, and `agent/sshserver/go.mod` the
  agent's SSH server's, `github.com/iffiX/neutrino/agent/sshserver`
  ([../design/agent/modules/ssh_server.md](../design/agent/modules/ssh_server.md));
  the two share no code. A dependency is pinned at an exact version in
  `go.mod` and `go.sum` is committed; `go mod tidy` leaves both unchanged.
- The dependencies are few and each is named here with what it is for:
  `github.com/flynn/noise` for the Noise handshake,
  `github.com/libp2p/go-yamux/v4` for the sessions, `golang.org/x/crypto`
  for the primitives and, in the SSH server, its `ssh` package,
  `github.com/pkg/sftp` for the SSH server's sftp subsystem, and
  `golang.org/x/mobile` for the Android and iOS bindings. Adding one is a decision for the user
  ([../design/min_support.md](../design/min_support.md)).
- `CGO_ENABLED=0` for every binary, so one static file per platform;
  `packaging/build` cross-compiles them and stamps the version with
  `-ldflags "-X"`. Nothing in the module reads its version from a file.

## Files and directories

- A directory is one Go package, named in lowercase with no underscore, as
  Go asks: `transport/knock/`, `transport/handshake/`, `transport/session/`,
  `transport/relay/`, `transport/control/`, `transport/cmd/neutrino_transport/`,
  `transport/mobile/`, and `transport/tests/` for what crosses packages, a
  hub's and a peer's transports talking over loopback with the Python sides
  faked on their local channels. This is the one place the repository departs from
  `under_score` directory names ([layout_style.md](layout_style.md)), because
  a Go package name is its directory name.
- A file is named after its one concept in `under_score`, as Go's own files
  are: `relay_session.go`, `cookie_jar.go`. One file holds one type and what
  belongs to it, or one group of functions on one concept.
- No grab-bag files or packages: no `util.go`, no `common/`, no `helpers/`.
- Non-configurable constants live in one `constants.go` per package, as
  `const` in CamelCase with the domain prefix: `KnockLength`,
  `SessionWindowBytes`, `ControlLineLimit`.

## Naming

- Exported identifiers are CamelCase, unexported ones camelCase, as Go
  asks; the `under_score` rule of the repository stops at the file name.
- Booleans read as questions: `isAdmitted`, `HasCookie()`. A field decoded
  from a wire message is the CamelCase form of that field (`is_token_required`
  becomes `IsTokenRequired`), mapped once in its `json` tag.
- Types follow the `<Domain><Thing><Role>` families of
  [../design/class_hierarchy.md](../design/class_hierarchy.md): `RelaySession`,
  `KnockVerifier`, `ControlListener`. An interface with one method is named
  by that method with `-er`, as Go does: `Admitter`, `Dialer`.
- A package is never named after a layer (`core`, `base`, `internal` holds
  nothing of its own); it is named after the one thing it does.

## Comments

- English only, stating the fact, with no narrated reasoning
  ([comment_style.md](comment_style.md)).
- Every exported identifier has a doc comment that starts with its name, as
  `go doc` expects. A function's comment says what it does, what it returns,
  and the errors it returns on purpose, in prose: `It returns ErrSessionClosed
  once Close has been called.` That is the same contract as Python's `Args:`,
  `Returns:` and `Raises:`; Go has no sections for them, so the sentences
  carry it.
- A package has one `doc.go` with the package comment: what the package is,
  in a paragraph.

## Errors

- Go's own errors first: `io.EOF` at the end of a stream, `os.ErrNotExist` for
  a missing file, `context.Canceled` and `context.DeadlineExceeded` for a
  stop, `net.Error` for the network.
- Kinds of the package's own are declared in one `errors.go` per package and
  nowhere else: a sentinel `var ErrSessionClosed = errors.New("session closed")`
  for a condition with no detail, a struct type for one that carries detail.
  A kind is named after what happened, never after a layer.
- Every error returned up is wrapped with `%w` and the thing it concerns:
  `fmt.Errorf("dial %s: %w", address, err)`. A caller checks with
  `errors.Is` or `errors.As`, never by comparing strings.
- A refusal from the hub is the typed error `*Refusal{Code, Params}`, the
  `{code, params}` shape of [../design/protocol.md](../design/protocol.md),
  checked with `errors.As`. The Python side receives it as that shape over the
  control channel and words it.
- No `panic` outside `main` and the tests, and no `log.Fatal` in a package: a
  fault is an error returned to whoever can act on it. A `recover` exists
  nowhere.

## Concurrency

- Every goroutine has an owner that can stop it: it takes a `context.Context`
  and returns when the context ends. No goroutine is started without the
  line that ends it being visible in the same type.
- A channel is closed by its one sender. A field read from several
  goroutines says which mutex guards it in the comment above the field.
- Buffers for a stream's copy come from a `sync.Pool` sized to the yamux
  window; no copy allocates per frame.

## File internal order

Package comment (in `doc.go`), then imports in three groups separated by a
blank line (standard library, third-party, this module), then constants,
then package variables, then types, then constructors (`New…`), then
exported methods, then unexported methods, then functions. A `main.go`
holds `main` and flag parsing and nothing else.

## Tests

- `go test -race ./...`. A file `relay_session.go` is tested by
  `relay_session_test.go` beside it in the same package; the mirror rule of
  [../design/tests.md](../design/tests.md) applies unchanged.
- A test is a table test where the cases are the same shape; each case is
  named, and the name is what the failure prints.
- The frames the transport carries for the Python side are checked against
  `hub/tests/web/channel_schema.json`, the golden the hub's own tests pin;
  the handshake is checked against test vectors kept beside the package.
- A test touches no network interface but loopback and starts no process
  but its own ([../design/tests.md](../design/tests.md)).

## Logging

- A package logs nothing. The binary in `cmd/` writes one line per event to
  standard error, `key=value` pairs after a short verb, and systemd or the
  agent's log reader collects it. No log library is added for this.

package control

import "time"

const (
	// ControlQuestionTimeout is the wait for the Python's answer to a question.
	ControlQuestionTimeout = 5 * time.Second
	// ControlSecretTimeout bounds a connection's first line, the secret.
	ControlSecretTimeout = time.Second // scan: allow
	// ControlSecretChars is the secret's length in hex characters.
	ControlSecretChars = 64
	// ControlLineLimit bounds one line, a frame's size and a little more.
	ControlLineLimit = 2*1024*1024 + 4096
	// ControlSocketMode is the Unix socket's mode and ControlSocketDirMode
	// its directory's when the transport makes it.
	ControlSocketMode    = 0o600
	ControlSocketDirMode = 0o700
	// ControlPipePrefix tells a Windows named pipe from a socket path.
	ControlPipePrefix = `\\.\pipe\`
	// ControlMoveGrace is how long a moved-off session is kept after the new
	// session's first frame from the hub.
	ControlMoveGrace = 2 * time.Second
)

// The connection kinds a first line names.
const (
	OpControl = "control"
	OpAttach  = "attach"
	OpOpen    = "open"
)

// The roles a peer's transport runs as.
const (
	RoleAgent  = "agent"
	RoleClient = "client"
)

// The paths a client's candidate names, best first.
const (
	PathLan       = "lan"
	PathDirect    = "direct"
	PathNetbird   = "netbird"
	PathEasytier  = "easytier"
	PathSshRelay  = "ssh_relay"
	PathSakuraFrp = "sakurafrp"
	PathOpenFrp   = "openfrp"
)

// The commands the Python sends.
const (
	CommandSessionClose = "session_close"
	CommandStreamsClose = "streams_close"
	CommandKeysReload   = "keys_reload"
	CommandSharesSet    = "shares_set"
	CommandDial         = "dial"
	CommandUndial       = "undial"
	CommandRound        = "round"
	CommandJoin         = "join"
	CommandLeave        = "leave"
	CommandForwardStart = "forward_start"
	CommandForwardStop  = "forward_stop"
)

// The events the transport sends.
const (
	EventSessionOpen = "session_open"
	EventSessionEnd  = "session_end"
	EventStream      = "stream"
	EventRoundEnd    = "round_end"
	EventForwardEnd  = "forward_end"
)

// The questions the transport asks.
const (
	QuestionPeer   = "peer"
	QuestionTicket = "ticket"
	QuestionEntry  = "entry"
	QuestionToken  = "token"
	QuestionPort   = "port"
	QuestionGuest  = "guest"
)

// The codes the local channel says itself.
const (
	CodeCommandUnknown = "command_unknown"
	CodeBindingUnknown = "binding_unknown"
	CodeSessionUnknown = "session_unknown"
	CodeStreamUnknown  = "stream_unknown"
	CodeNoSession      = "no_session"
	CodeForwardUnknown = "forward_unknown"
	CodeBodyInvalid    = "body_invalid"
)

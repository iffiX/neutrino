"""Fixed values of the channel: its number, its words, its limits and its codes."""

from neutrino_hub.utils.constants import UTILS_STATE_ROOT

# The protocol number this hub speaks, and the oldest it still accepts. One
# number has one name in every package, so neither carries a package prefix.
PROTOCOL = 3
PROTOCOL_MIN = 3

# An enrolment ticket: its size in bytes before encoding, and how long it
# lives, counted across hub restarts. The standard names both, so neither
# carries a package prefix.
ENROLLMENT_TOKEN_BYTES = 18
ENROLLMENT_TTL_S = 30 * 60
# The open tickets, each as its SHA-256, mode 0600.
CHANNEL_TICKET_PATH = UTILS_STATE_ROOT / "enrollment_tickets.json"
CHANNEL_TICKET_FILE_MODE = 0o600

# Who is on the other end of a socket, and what the hub answers as.
CHANNEL_ROLE_AGENT = "agent"
CHANNEL_ROLE_CLIENT = "client"
CHANNEL_ROLE_HUB = "hub"

# The three endpoints on the agent port.
CHANNEL_JOIN_PATH = "/api/channel/join"
CHANNEL_LEAVE_PATH = "/api/channel/leave"
CHANNEL_WS_PATH = "/api/channel/socket"

# Close codes: a refused hello, and a socket replaced by a second one for the
# same binding.
CHANNEL_CLOSE_REFUSED = 4000
CHANNEL_CLOSE_REPLACED = 4010

# The frame words.
CHANNEL_FRAME_HELLO = "hello"
CHANNEL_FRAME_WELCOME = "welcome"
CHANNEL_FRAME_REFUSED = "refused"
CHANNEL_FRAME_STATE = "state"
CHANNEL_FRAME_REPORT = "report"
CHANNEL_FRAME_OPEN = "open"
CHANNEL_FRAME_CLOSE = "close"
CHANNEL_FRAME_CREDIT = "credit"

# The stream kinds.
CHANNEL_STREAM_SHELL = "shell"
CHANNEL_STREAM_FILE = "file"
CHANNEL_STREAM_COMMAND = "command"
CHANNEL_STREAM_PACKAGE = "package"
CHANNEL_STREAM_LOG = "log"
CHANNEL_STREAM_SERVICE = "service"
CHANNEL_STREAM_CONNECT = "connect"

# A ``shell`` inside a container names the module that runs it.
CHANNEL_SHELL_CONTAINER_MODULE = "podman"

# The operations a ``file`` stream's ``op`` names.
CHANNEL_FILE_OP_LIST = "list"
CHANNEL_FILE_OP_DOWNLOAD = "download"
CHANNEL_FILE_OP_UPLOAD = "upload"
CHANNEL_FILE_OP_RENAME = "rename"
CHANNEL_FILE_OP_REMOVE = "remove"
CHANNEL_FILE_OP_DIRECTORY_CREATE = "directory_create"
CHANNEL_FILE_OP_DIRECTORY_DOWNLOAD = "directory_download"

# The ``module`` a ``command`` names for the agent's own verbs, and the two
# verbs the hub sends outside a module's router: a shell's later size, and
# the two every module answers, a configuration checked before it is stored
# and the tail of the module's units' journal.
CHANNEL_COMMAND_MODULE_AGENT = "agent"
CHANNEL_VERB_RESIZE = "resize"
CHANNEL_VERB_VALIDATE = "validate"
CHANNEL_VERB_JOURNAL = "journal"
# The two verbs on a shell session: whether it outlives its streams and
# whether others see it, and ending it. Both name the session by the id its
# opener generated.
CHANNEL_VERB_PERSIST = "persist"
CHANNEL_VERB_STOP_SESSION = "stop_session"
# The owner the hub stamps on a kept shell's open: the panel's own, or a
# client's as the prefix followed by its id.
CHANNEL_SHELL_OWNER_HUB = "hub"
CHANNEL_SHELL_OWNER_CLIENT_PREFIX = "client:"

# The hub allots even stream ids from here; a peer's ids are odd.
CHANNEL_FIRST_HUB_STREAM_ID = 0

# A binary frame is a big-endian u32 stream id, then the bytes.
CHANNEL_STREAM_ID_BYTES = 4
# What a stream may have in flight before the receiving side grants more.
CHANNEL_STREAM_CREDIT_BYTES = 1024 * 1024
# The largest binary frame either side sends on one stream.
CHANNEL_CHUNK_BYTES = 64 * 1024
# How long a fresh socket may stay silent before its hello is due.
CHANNEL_HELLO_TIMEOUT_S = 10.0
# How long a call from a thread waits on the loop before it is given up.
CHANNEL_CALL_TIMEOUT_S = 15.0
# Protocol-level keepalive: uvicorn pings on this interval and drops a
# socket whose pong is late by this much.
CHANNEL_PING_INTERVAL_S = 20.0
CHANNEL_PING_TIMEOUT_S = 20.0
# How long the hub waits for the far end of a ``connect`` stream it dials.
CHANNEL_CONNECT_DIAL_TIMEOUT_S = 10.0
# How many ``connect`` streams one client socket may hold open at once.
CHANNEL_CONNECT_STREAMS_MAX = 256
# A UDP stream's far end: how long a source keeps its socket with no
# datagram either way, and how many sources one stream keeps a socket for.
CHANNEL_UDP_IDLE_TIMEOUT_S = 60.0
CHANNEL_UDP_SOURCES_MAX = 64
# Datagrams the hub holds for an agent's UDP stream before that stream's
# first credit; more are dropped. The clients hold as many before the
# hub's.
CHANNEL_UDP_HELD_DATAGRAMS_MAX = 16
# A UDP frame's source port in front of its datagram, big-endian.
CHANNEL_UDP_SOURCE_BYTES = 2
# The loopback address the hub dials its own gateway and panel on.
CHANNEL_CONNECT_LOOPBACK = "127.0.0.1"
# The agent port's limits, each over the whole port and never per peer
# address (connection.md, "What an unadmitted peer can cost the hub"): a
# socket's time to its first byte, a TLS handshake's time from that byte,
# the time from accept to an admitted hello, the connections not yet past
# hello, the sockets past it, and the failed admissions within the window
# that pause join.
CHANNEL_FIRST_BYTE_TIMEOUT_S = 3.0
CHANNEL_TLS_HANDSHAKE_TIMEOUT_S = 10.0
CHANNEL_ADMISSION_TIMEOUT_S = 30.0
CHANNEL_UNADMITTED_MAX = 128
CHANNEL_SOCKETS_MAX = 512
CHANNEL_ADMISSION_FAILURES_MAX = 30
CHANNEL_ADMISSION_WINDOW_S = 60.0
# The largest WebSocket message the agent port takes, admitted or not. Four
# times the largest message measured on a hub of 64 machines with every
# module and 32 shares, 256 entries and every terminal, rounded up to a power
# of two: a client's state 274 KB, a command's close 98 KB, an agent's report
# 74 KB, a data frame 64 KB, an agent's state 40 KB
# (tests/web/test_channel_message_size.py).
CHANNEL_MESSAGE_BYTES_MAX = 2 * 1024 * 1024
# The largest body a join or a leave may carry.
CHANNEL_REQUEST_BYTES_MAX = 64 * 1024

# The codes a refusal or a close carries.
CHANNEL_CODE_PROTOCOL_TOO_OLD = "protocol_too_old"
CHANNEL_CODE_PROTOCOL_TOO_NEW = "protocol_too_new"
CHANNEL_CODE_KIND_UNKNOWN = "kind_unknown"
CHANNEL_CODE_VERB_UNKNOWN = "verb_unknown"
# A client's resize names a shell stream it has no bridge open on.
CHANNEL_CODE_SHELL_UNKNOWN = "shell_unknown"
# A session verb names a session no online machine reports, or a persist
# comes from a viewer that did not open the session.
CHANNEL_CODE_SESSION_UNKNOWN = "session_unknown"
CHANNEL_CODE_SESSION_NOT_OWNED = "session_not_owned"
CHANNEL_CODE_REPLACED = "replaced"
CHANNEL_CODE_BINDING_UNKNOWN = "binding_unknown"
CHANNEL_CODE_TICKET_SPENT = "ticket_spent"
CHANNEL_CODE_ROLE_MISMATCH = "role_mismatch"
# A first frame that is late, not text, not a hello, or not one this hub reads.
CHANNEL_CODE_HELLO_INVALID = "hello_invalid"
# A hello past the cap on channel sockets, and a join while failed
# admissions are at their limit.
CHANNEL_CODE_CHANNEL_FULL = "channel_full"
CHANNEL_CODE_ADMISSION_PAUSED = "admission_paused"
# A join or a leave whose body is past CHANNEL_REQUEST_BYTES_MAX.
CHANNEL_CODE_REQUEST_TOO_LARGE = "request_too_large"
# What a request gets when the machine it went to never answered it: the
# stream ran out of time, or the loop did. It is a display code, worded by
# the panel as the word for a machine that has not reported.
CHANNEL_CODE_NEVER_REPORTED = "agent_never_reported"
# A ``connect`` past the socket's limit, and a dial that failed, with its
# reason.
CHANNEL_CODE_CONNECT_LIMIT = "connect_limit"
CHANNEL_CODE_CONNECT_FAILED = "connect_failed"
CHANNEL_CONNECT_REFUSED = "refused"
CHANNEL_CONNECT_TIMEOUT = "timeout"
CHANNEL_CONNECT_UNREACHABLE = "unreachable"

# The state an agent reports for a module. The first four are also the
# words ``want`` takes.
CHANNEL_MODULE_STATE_ABSENT = "absent"
CHANNEL_MODULE_STATE_INSTALLED = "installed"
CHANNEL_MODULE_STATE_STOPPED = "stopped"
CHANNEL_MODULE_STATE_RUNNING = "running"
CHANNEL_MODULE_STATE_INSTALLING = "installing"
CHANNEL_MODULE_STATE_UNINSTALLING = "uninstalling"
CHANNEL_MODULE_STATE_FAILED = "failed"
CHANNEL_MODULE_STATE_UNSUPPORTED = "unsupported"
CHANNEL_MODULE_WANTS = (
    CHANNEL_MODULE_STATE_ABSENT,
    CHANNEL_MODULE_STATE_INSTALLED,
    CHANNEL_MODULE_STATE_STOPPED,
    CHANNEL_MODULE_STATE_RUNNING,
)
# The wants under which the agent applies the hub's configuration.
CHANNEL_MODULE_CONFIGURED_WANTS = (
    CHANNEL_MODULE_STATE_STOPPED,
    CHANNEL_MODULE_STATE_RUNNING,
)
# The states in which the software is on the machine.
CHANNEL_MODULE_PRESENT_STATES = (
    CHANNEL_MODULE_STATE_INSTALLED,
    CHANNEL_MODULE_STATE_STOPPED,
    CHANNEL_MODULE_STATE_RUNNING,
)
CHANNEL_MODULE_STATES = CHANNEL_MODULE_WANTS + (
    CHANNEL_MODULE_STATE_INSTALLING,
    CHANNEL_MODULE_STATE_UNINSTALLING,
    CHANNEL_MODULE_STATE_FAILED,
    CHANNEL_MODULE_STATE_UNSUPPORTED,
)

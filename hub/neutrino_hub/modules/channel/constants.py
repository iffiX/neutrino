"""Fixed values of the channel: its number, its words, its limits and its codes."""

# The protocol number this hub speaks, and the oldest it still accepts. One
# number has one name in every package, so neither carries a package prefix.
PROTOCOL = 1
PROTOCOL_MIN = 1

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
CHANNEL_STREAM_DESKTOP = "desktop"

# A binary frame is a big-endian u32 stream id, then the bytes.
CHANNEL_STREAM_ID_BYTES = 4
# What a stream may have in flight before the receiving side grants more.
CHANNEL_STREAM_CREDIT_BYTES = 1024 * 1024
# The largest binary frame either side sends on one stream.
CHANNEL_CHUNK_BYTES = 64 * 1024
# How long a fresh socket may stay silent before its hello is due.
CHANNEL_HELLO_TIMEOUT_S = 10.0
# How long the hub waits for the other side to answer an open.
CHANNEL_OPEN_TIMEOUT_S = 15.0
# Protocol-level keepalive: uvicorn pings on this interval and drops a
# socket whose pong is late by this much.
CHANNEL_PING_INTERVAL_S = 20.0
CHANNEL_PING_TIMEOUT_S = 20.0

# The codes a refusal or a close carries.
CHANNEL_CODE_PROTOCOL_TOO_OLD = "protocol_too_old"
CHANNEL_CODE_PROTOCOL_TOO_NEW = "protocol_too_new"
CHANNEL_CODE_KIND_UNKNOWN = "kind_unknown"
CHANNEL_CODE_VERB_UNKNOWN = "verb_unknown"
CHANNEL_CODE_REPLACED = "replaced"
CHANNEL_CODE_BINDING_UNKNOWN = "binding_unknown"
CHANNEL_CODE_TICKET_SPENT = "ticket_spent"
CHANNEL_CODE_ROLE_MISMATCH = "role_mismatch"

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
CHANNEL_MODULE_STATES = CHANNEL_MODULE_WANTS + (
    CHANNEL_MODULE_STATE_INSTALLING,
    CHANNEL_MODULE_STATE_UNINSTALLING,
    CHANNEL_MODULE_STATE_FAILED,
    CHANNEL_MODULE_STATE_UNSUPPORTED,
)

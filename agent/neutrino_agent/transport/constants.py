"""Fixed values of the local channel to the agent's transport."""

# The program, under the platform's ``agent_bin_dir``, and how it is started
# for the agent: ``neutrino_transport agent --listen <socket or pipe>``, the
# secret as the first line of its standard input, which stays open; the
# transport exits when it ends.
TRANSPORT_PROGRAM_NAME = "neutrino_transport"
TRANSPORT_PROGRAM_NAME_WINDOWS = "neutrino_transport.exe"
TRANSPORT_ROLE_ARGUMENT = "agent"
TRANSPORT_LISTEN_OPTION = "--listen"
# The listener the service's transport serves, by system.
TRANSPORT_SOCKET_PATH = "/run/neutrino/agent/transport.sock"
TRANSPORT_SOCKET_PATH_DARWIN = "/var/run/neutrino/agent/transport.sock"
TRANSPORT_PIPE_PREFIX = "\\\\.\\pipe\\"
TRANSPORT_PIPE_NAME = TRANSPORT_PIPE_PREFIX + "neutrino_agent_transport"
# A ``nagent join``, ``leave`` or ``status`` runs a transport of its own
# beside the service's, on a listener named after its process.
TRANSPORT_ONE_SHOT_SUFFIX = "_{pid}"
TRANSPORT_SOCKET_SUFFIX = ".sock"
# How long a start waits for the listener to answer, and how often it looks.
TRANSPORT_START_TIMEOUT_S = 10.0
TRANSPORT_START_POLL_S = 0.05
# How long a stopped transport may take to exit before it is killed.
TRANSPORT_STOP_TIMEOUT_S = 5.0
# The secret: 32 random bytes, written as 64 hex characters.
TRANSPORT_SECRET_BYTES = 32

# The three kinds of local connection, by their first line's ``op``.
TRANSPORT_OP_CONTROL = "control"
TRANSPORT_OP_ATTACH = "attach"
TRANSPORT_OP_OPEN = "open"
# The largest line on the control connection, and the largest record's
# payload on a stream's connection: ``ControlFrameBytesMax`` and
# ``RecordBytesMax``.
TRANSPORT_LINE_BYTES_MAX = 2 * 1024 * 1024
TRANSPORT_RECORD_BYTES_MAX = 64 * 1024
# How long a command waits for the transport's answer, and a question for
# this side's: ``ControlQuestionTimeout`` bounds the transport's own wait.
TRANSPORT_COMMAND_TIMEOUT_S = 30.0
TRANSPORT_JOIN_TIMEOUT_S = 120.0

# The record types a stream carries.
TRANSPORT_RECORD_OPEN = 1
TRANSPORT_RECORD_ACCEPT = 2
TRANSPORT_RECORD_DATA = 3
TRANSPORT_RECORD_STDERR = 4
TRANSPORT_RECORD_EOF = 5
TRANSPORT_RECORD_RESIZE = 6
TRANSPORT_RECORD_DATAGRAM = 7
TRANSPORT_RECORD_CLOSE = 8

# The code a question this side cannot answer in time, or a stream that
# cannot be attached, comes to.
TRANSPORT_CODE_CONTROL_UNAVAILABLE = "control_unavailable"

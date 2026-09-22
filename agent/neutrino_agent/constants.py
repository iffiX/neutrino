"""Fixed values of the agent.

Anything an operator changes lives in ``/etc/neutrino/agent/agent.json``; this
file holds only what is wired into the protocol.
"""

# The hub and the agent share one configuration root with a directory each,
# so a machine running both has one place to look and one place to back up.
AGENT_CONFIG_PATH = "/etc/neutrino/agent/agent.json"

AGENT_SERVICE_NAME = "neutrino_agent.service"

# The protocol number this build speaks. The name has no package prefix:
# one number has one name in every package.
PROTOCOL = 1
# What this side answers as, in the join body and the hello, and what the
# hub answers as in its welcome.
AGENT_ROLE = "agent"
AGENT_HUB_ROLE = "hub"
# What ``software`` reads before the version, on each side of the channel.
AGENT_SOFTWARE_PREFIX = "neutrino_agent/"
AGENT_HUB_SOFTWARE_PREFIX = "neutrino_hub/"

# The channel's three endpoints, all on the agent TLS port: joining and
# leaving are HTTP, and everything else rides the one socket.
CHANNEL_JOIN_PATH = "/api/channel/join"
CHANNEL_LEAVE_PATH = "/api/channel/leave"
AGENT_WS_PATH = "/api/channel/socket"
# How long the socket may stay silent before it is taken for dead. The hub
# pings well inside this.
AGENT_WS_SILENCE_TIMEOUT_S = 45
# A binary frame starts with the stream id, a big-endian unsigned integer
# of this many bytes.
AGENT_WS_STREAM_ID_BYTES = 4
# The largest binary frame either side sends on one stream.
AGENT_WS_CHUNK_BYTES = 64 * 1024
# What the hub may send on one stream before this side grants more: one
# window of bytes, offered when a stream that takes bytes opens.
AGENT_WS_STREAM_CREDIT_BYTES = 1024 * 1024
# How long a stream waits on the hub's credit before it stops trying.
AGENT_WS_CREDIT_TIMEOUT_S = 60
# Close codes: a refused hello, after the ``refused`` frame that says why,
# and a socket replaced by a second one for the same binding.
AGENT_WS_CLOSE_REFUSED = 4000
AGENT_WS_CLOSE_REPLACED = 4010
# The codes the channel itself gives a refusal: a 4000 close with no
# ``refused`` frame before it, a socket replaced by a second one, and the
# one refusal that unbinds, which only the pinned hub can say.
AGENT_CODE_CHANNEL_REFUSED = "channel_refused"
AGENT_CODE_REPLACED = "replaced"
AGENT_CODE_BINDING_UNKNOWN = "binding_unknown"

# How much of a failed step's output a code's params carry. Enough to read
# the package manager's own complaint, bounded so a verbose failure cannot
# fill a report.
AGENT_MODULE_OUTPUT_LIMIT_BYTES = 16 * 1024

# The module a command names for the agent's own verbs, and the one verb
# every module answers: checking a configuration before the hub stores it.
AGENT_COMMAND_MODULE = "agent"
AGENT_MODULE_VERB_VALIDATE = "validate"
AGENT_MODULE_VERB_JOURNAL = "journal"
# How many lines of a module's units' journal one read returns at most.
AGENT_MODULE_JOURNAL_LINES = 200

# What the hub's state may want a module to be. The agent makes each
# mentioned module's actual state equal its want.
AGENT_WANT_ABSENT = "absent"
AGENT_WANT_INSTALLED = "installed"
AGENT_WANT_STOPPED = "stopped"
AGENT_WANT_RUNNING = "running"
# What the agent reports a module to be, one closed table on every surface:
# four steady states, two in transit, and two shared by every failure.
AGENT_MODULE_STATE_ABSENT = "absent"
AGENT_MODULE_STATE_INSTALLED = "installed"
AGENT_MODULE_STATE_STOPPED = "stopped"
AGENT_MODULE_STATE_RUNNING = "running"
AGENT_MODULE_STATE_INSTALLING = "installing"
AGENT_MODULE_STATE_UNINSTALLING = "uninstalling"
AGENT_MODULE_STATE_FAILED = "failed"
AGENT_MODULE_STATE_UNSUPPORTED = "unsupported"

# The transient unit a self-update runs in. Installing the package restarts
# neutrino_agent.service, so the install must outlive the process that
# started it.
AGENT_UPDATE_UNIT = "neutrino_agent_update"
AGENT_UPDATE_LAUNCH_TIMEOUT_S = 30

# How often a report goes up while nothing changes. Every report carries
# the machine's metrics, which the panel draws live, so this is the rate
# those readings arrive at.
AGENT_REPORT_INTERVAL_S = 5
AGENT_REQUEST_TIMEOUT_S = 10
# Backoff bounds used when the gateway is unreachable. Starting at one interval
# and doubling to a minute keeps a rebooting gateway from being hammered while
# still reconnecting promptly once it returns.
AGENT_BACKOFF_MIN_S = 5
AGENT_BACKOFF_MAX_S = 60
# How long a connection round waits between an address that did not answer
# and the next one. A whole round failing is what backs off.
AGENT_ROTATE_DELAY_S = 1
# The name every network the hub serves resolves to the hub's address on that
# network. It is the first address a round connects to.
AGENT_HUB_NAME = "hub.neutrino.internal"

AGENT_COMMAND_TIMEOUT_S = 900
AGENT_OUTPUT_LIMIT_BYTES = 64 * 1024

# The shell a stream opens for the hub: this account's own where it is
# usable, else the first of these.
AGENT_SHELL_FALLBACKS = ("/bin/bash", "/bin/sh")
AGENT_SHELL_READ_BYTES = 4096
# How long a shell's process group may take to die after the hub closes
# the stream, per signal.
AGENT_SHELL_KILL_TIMEOUT_S = 2.0
# How long a signalled process may take to leave before it is killed.
AGENT_KILL_GRACE_S = 2.0

# How long a stepped-down account command may take.
AGENT_STEP_DOWN_TIMEOUT_S = 120

# The local control channel: a socket the agent serves as root. Its file is
# 0600 under a 0700 directory, so only root reaches it.
AGENT_CONTROL_SOCKET_PATH = "/run/neutrino_agent/agent.sock"
AGENT_CONTROL_REQUEST_TIMEOUT_S = 5
# An action the agent carries out before answering, such as sharing the
# desktop, takes longer than a read; the CLI waits this long for one.
AGENT_CONTROL_ACTION_TIMEOUT_S = 60

# Where the machine keeps what it decided for itself, and the directory
# holding the one secret that never enters it: the desktop's seat password,
# in its own root-only file. The directory both live in is the platform
# contract's ``agent_data_dir``; these are the POSIX paths, which double as
# the defaults where nothing wires a root in.
AGENT_DATA_DIR_POSIX = "/etc/neutrino/agent"
AGENT_STATE_NAME = "state.json"
AGENT_CREDENTIALS_DIR_NAME = "credentials"
AGENT_STATE_PATH = AGENT_DATA_DIR_POSIX + "/" + AGENT_STATE_NAME

# The hub's desired state for this machine, kept beside the state store so
# the last copy taken is readable after a restart. Root-only: a module's
# configuration carries the secrets its service signs with.
AGENT_DESIRED_STATE_NAME = "desired.json"
AGENT_DESIRED_STATE_PATH = AGENT_DATA_DIR_POSIX + "/" + AGENT_DESIRED_STATE_NAME

# What the last reinstall did, written beside the state by the transient
# unit the install ran in and read by the agent that install put here. Both
# files are root-only: the package manager's output is nobody else's.
AGENT_REINSTALL_RESULT_NAME = "reinstall.json"
AGENT_REINSTALL_LOG_NAME = "reinstall.log"
# How much of the install log the result carries up.
AGENT_REINSTALL_OUTPUT_LIMIT_BYTES = 4 * 1024

# How long a module's live details stand in the report before the engine
# reads them again. The reporter never waits on a read.
AGENT_MODULE_DETAILS_TTL_S = 5.0

# Where the agent's own RustDesk build lands. The module is built in: its
# row reads installed while this file exists, and no order moves it. Under
# /usr because RustDesk refuses `--password` unless its own `current_exe`
# is there, and it resolves symlinks before it looks.
AGENT_RUSTDESK_BINARY_PATH = "/usr/lib/neutrino_agent/rustdesk/rustdesk"
# How long a module command waits for a pending desired state to apply
# before it runs against the configuration that state carries.
AGENT_MODULE_COMMAND_SETTLE_S = 30.0

# What this machine keeps about its own work, root-only: the configured
# marks, and a package in transit.
AGENT_VAR_DIR = "/var/lib/neutrino_agent"
# Where the mark that the hub has configured a module lives, one root-only
# file per module. Written on the first successful apply of the hub's
# configuration, deleted on uninstall; it tells ``installed`` from
# ``stopped`` and ``running``.
AGENT_CONFIGURED_DIR = AGENT_VAR_DIR + "/configured"
# Where a package coming down a stream lands until its digest is checked.
# A module's package is deleted once its install ran; the agent's own
# outlives the process that received it, and the agent the install put
# here clears the directory when it starts.
AGENT_PACKAGE_DIR = AGENT_VAR_DIR + "/packages"

"""Fixed values of the agent.

Anything an operator changes lives in ``agent.json`` under the agent's data
root, ``/etc/neutrino/agent`` on Linux; this file holds only what is wired
into the protocol.
"""

# The binding file, under the platform's data root. On Linux the hub and the
# agent share one configuration root with a directory each, so a machine
# running both has one place to look and one place to back up.
AGENT_CONFIG_NAME = "agent.json"

AGENT_SERVICE_NAME = "neutrino_agent.service"
# The agent's service as the Windows service control manager knows it, and
# as launchd knows it on macOS, with the plist that declares it.
AGENT_WINDOWS_SERVICE_NAME = "neutrino_agent"
AGENT_LAUNCHD_LABEL = "com.neutrino.agent"
AGENT_LAUNCHD_PLIST_PATH = "/Library/LaunchDaemons/com.neutrino.agent.plist"
# How long the service, once asked to stop, waits for the agent's loop to
# end before it reports stopped and exits; under the 30 s wait hint.
AGENT_SERVICE_STOP_WAIT_S = 25
# The agent's own log where no journal keeps it: a file under the log root
# on Windows, and the file the LaunchDaemon's output goes to on macOS.
AGENT_WINDOWS_LOG_NAME = "agent.log"
AGENT_DARWIN_LOG_PATH = "/Library/Logs/Neutrino/agent/agent.log"

# The protocol number this build speaks. The name has no package prefix:
# one number has one name in every package.
PROTOCOL = 3
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
# How long a ``connect`` stream waits for the port it dials on this machine.
AGENT_CONNECT_DIAL_TIMEOUT_S = 10
# The address a ``connect`` stream dials, unless a container port is
# published on one address of its own.
AGENT_CONNECT_LOOPBACK = "127.0.0.1"
# What a ``connect`` stream closes with when it dials nothing: a port this
# machine does not publish now, and a dial that failed, with its reason.
AGENT_CODE_PORT_NOT_PUBLISHED = "port_not_published"
AGENT_CODE_CONNECT_FAILED = "connect_failed"
AGENT_CONNECT_REFUSED = "refused"
AGENT_CONNECT_TIMEOUT = "timeout"
AGENT_CONNECT_UNREACHABLE = "unreachable"
# The two protocols a ``connect`` stream carries; an open that names none
# is TCP.
AGENT_CONNECT_TCP = "tcp"
AGENT_CONNECT_UDP = "udp"
# A UDP stream's far end: how long a source's socket lives with no
# datagram either way, and how many sources one stream keeps a socket for.
# The hub's own values, CHANNEL_UDP_IDLE_TIMEOUT_S and
# CHANNEL_UDP_SOURCES_MAX.
AGENT_UDP_IDLE_TIMEOUT_S = 60
AGENT_UDP_SOURCES_MAX = 64
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
# How many lines of a module's log one read returns at most.
AGENT_MODULE_JOURNAL_LINES = 200
# How much of the end of a log file one read looks at, and how much a read
# for the lines naming one module looks at: more than the agent's own log
# holds before it is rotated.
AGENT_MODULE_LOG_TAIL_BYTES = 256 * 1024
AGENT_MODULE_LOG_SEARCH_BYTES = 2 * 1024 * 1024
# The agent's log as its last rotation left it, beside the one written now.
AGENT_LOG_ROTATED_SUFFIX = ".1"

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
# The shell a stream opens where the platform names its own, by
# ``sys.platform``: zsh as a login shell on a Mac, PowerShell on a pseudo
# console on Windows.
AGENT_SHELL_COMMANDS = {
    "darwin": ("/bin/zsh", "-il"),
    "win32": ("powershell.exe", "-NoLogo"),
}
AGENT_SHELL_READ_BYTES = 4096
# How long a shell's process group may take to die after the hub closes
# the stream, per signal.
AGENT_SHELL_KILL_TIMEOUT_S = 2.0
# How much of a shell's latest output is kept, and sent first to a stream
# that attaches to the running shell.
AGENT_SHELL_KEPT_BYTES = 256 * 1024
# How much output may wait for an attached stream before the shell's
# output is no longer read.
AGENT_SHELL_PENDING_BYTES = 1024 * 1024
# The account a shell runs as on Windows, where the agent is LocalSystem.
AGENT_SHELL_WINDOWS_ACCOUNT = "SYSTEM"
# How long a signalled process may take to leave before it is killed.
AGENT_KILL_GRACE_S = 2.0
# The pids the kill verb never ends: the idle process and init on every
# system, and Windows' System process.
AGENT_KILL_PROTECTED_PIDS = frozenset({0, 1, 4})

# How long a stepped-down account command may take.
AGENT_STEP_DOWN_TIMEOUT_S = 120
# A program answered on a terminal of its own: how long its question may
# take to show, how long its exit is waited for after the terminal ends, and
# how much one read takes.
AGENT_ANSWER_PROMPT_TIMEOUT_S = 10
AGENT_ANSWER_EXIT_TIMEOUT_S = 5
AGENT_ANSWER_READ_BYTES = 4096
# Windows runs a command as an account in a one-shot scheduled task: the
# task's name prefix, the directory under the state root that holds each
# account's script, input and output, how often the end is looked for, and
# the verb of the agent's own program that answers a question on a pseudo
# console inside such a task.
AGENT_RUN_AS_TASK_PREFIX = "neutrino_run_as_"
AGENT_RUN_AS_DIR_NAME = "run_as"
AGENT_RUN_AS_POLL_S = 0.5
AGENT_ANSWER_VERB = "answer"
AGENT_WINDOWS_PROGRAM_SUBDIR = ("Neutrino", "agent")
AGENT_WINDOWS_PROGRAM_FILES_DEFAULT = "C:\\Program Files"
AGENT_WINDOWS_BINARY_NAME = "nagent.exe"

# The local control channel: a socket the agent serves as root. Its file is
# 0600 under a 0700 directory, so only root reaches it.
AGENT_CONTROL_SOCKET_PATH = "/run/neutrino/agent/agent.sock"
# The same channel on macOS, and on Windows a named pipe whose security
# descriptor admits SYSTEM and the administrators alone.
AGENT_CONTROL_SOCKET_PATH_DARWIN = "/var/run/neutrino/agent/agent.sock"
AGENT_CONTROL_PIPE_PREFIX = "\\\\.\\pipe\\"
AGENT_CONTROL_PIPE_NAME = AGENT_CONTROL_PIPE_PREFIX + "neutrino_agent"
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
# The same root on macOS, and on Windows under %ProgramData%, whose value
# is read at run time and whose usual value stands in when it is unset. On
# Windows the agent's directory there holds the three roots by these names.
AGENT_DATA_DIR_DARWIN = "/Library/Application Support/Neutrino/agent/config"
AGENT_WINDOWS_PROGRAM_DATA_DEFAULT = "C:\\ProgramData"
AGENT_WINDOWS_AGENT_SUBDIR = ("Neutrino", "agent")
AGENT_WINDOWS_CONFIG_DIR_NAME = "config"
AGENT_WINDOWS_STATE_DIR_NAME = "state"
AGENT_WINDOWS_LOG_DIR_NAME = "log"
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
# How long the reinstall verb waits for the install's result before it
# closes as launched, and how often it looks; under the hub's own wait.
AGENT_REINSTALL_WAIT_S = 120.0
AGENT_REINSTALL_POLL_S = 1.0
# The exit statuses of an install that went through: msiexec's 3010 is one
# that finished with a restart owed.
AGENT_REINSTALL_INSTALLED_CODES = (0, 3010)

# How long a module's live details stand in the report before the engine
# reads them again. The reporter never waits on a read.
AGENT_MODULE_DETAILS_TTL_S = 5.0

# How long a module command waits for a pending desired state to apply
# before it runs against the configuration that state carries.
AGENT_MODULE_COMMAND_SETTLE_S = 30.0
# How often a state whose apply waits on a running install is applied again.
AGENT_MODULE_INSTALL_RECHECK_S = 30.0

# What this machine accumulated: the configured marks, a package in transit,
# the last reinstall's result, all root-only, and the software the hub sends
# for every account to run.
# The directory is the platform contract's ``agent_var_dir``; this is the
# Linux path, which doubles as the default where nothing wires one in.
AGENT_VAR_DIR = "/var/lib/neutrino/agent"
AGENT_VAR_DIR_DARWIN = "/Library/Application Support/Neutrino/agent/state"
# Where the mark that the hub has configured a module lives, one root-only
# file per module. Written on the first successful apply of the hub's
# configuration, deleted on uninstall; it tells ``installed`` from
# ``stopped`` and ``running``.
AGENT_CONFIGURED_DIR_NAME = "configured"
AGENT_CONFIGURED_DIR = AGENT_VAR_DIR + "/" + AGENT_CONFIGURED_DIR_NAME
# Where a package coming down a stream lands until its digest is checked.
# A module's package is deleted once its install ran; the agent's own
# outlives the process that received it, and the agent the install put
# here clears the directory when it starts.
AGENT_PACKAGE_DIR_NAME = "packages"
AGENT_PACKAGE_DIR = AGENT_VAR_DIR + "/" + AGENT_PACKAGE_DIR_NAME

# How many processes a report lists, the busiest first, on every system.
AGENT_PROCESS_TOP_COUNT = 12
# NVIDIA cards are read through the driver's own tool where it is installed.
AGENT_NVIDIA_SMI_COMMAND = (
    "nvidia-smi",
    "--query-gpu=name,utilization.gpu,memory.used,memory.total,"
    "temperature.gpu,power.draw",
    "--format=csv,noheader,nounits",
)
AGENT_NVIDIA_SMI_TIMEOUT_S = 4

# What removing the agent takes away is found by name. The units, scheduled
# tasks and firewall rules the modules add start with the first prefix, and
# their launchd jobs with the second; a name whose next word is another
# package's or the agent's own is not a module's.
AGENT_ADDED_NAME_PREFIX = "neutrino_"
AGENT_ADDED_LAUNCHD_PREFIX = "com.neutrino."
AGENT_ADDED_FOREIGN_WORDS = ("hub", "client", "agent")
# Where the modules write their units and their launchd jobs.
AGENT_SYSTEMD_UNIT_DIR = "/etc/systemd/system"
AGENT_LAUNCHD_DAEMON_DIR = "/Library/LaunchDaemons"
# The pf anchor the file share's fence on macOS lives under.
AGENT_PF_PARENT_ANCHOR = "com.apple"
# What a macOS removal takes besides the modules' jobs: the agent's own
# program, the link a terminal reaches it through, RustDesk as the package
# laid it down, and the package's receipt. The configuration, the state and
# the log stay, as a Linux package's removal leaves them.
AGENT_DARWIN_PROGRAM_DIR = "/Library/Application Support/Neutrino/agent/app"
AGENT_DARWIN_LINK_PATH = "/usr/local/bin/nagent"
AGENT_DARWIN_PACKAGE_ID = "com.neutrino.agent"
# The forwarders the agent keeps in front of a module's page (CloudCLI,
# code-server): how one request's head is read, how bytes are relayed, and
# how long a relayed connection may stay quiet.
AGENT_FORWARD_HEAD_LIMIT_BYTES = 65536
AGENT_FORWARD_CHUNK_BYTES = 65536
AGENT_FORWARD_UPSTREAM_TIMEOUT_S = 10.0
AGENT_FORWARD_IDLE_TIMEOUT_S = 3600.0
# The token a client opens such a page with: ``?tkn=`` holding
# ``base64url(expiry || nonce || HMAC-SHA256(secret, expiry || nonce))``,
# the expiry eight bytes big-endian in seconds since the epoch. A token
# whose expiry is further ahead than the horizon is refused, so the nonces
# held stay few.
AGENT_FORWARD_TOKEN_PARAMETER = "tkn"
AGENT_FORWARD_TOKEN_EXPIRY_BYTES = 8
AGENT_FORWARD_TOKEN_NONCE_BYTES = 16
AGENT_FORWARD_TOKEN_MAC_BYTES = 32
AGENT_FORWARD_TOKEN_HORIZON_S = 300
# The archive kinds a module's software from the hub comes in, as its
# manifest names them.
AGENT_PACKAGE_KIND_TAR = "tar"
AGENT_PACKAGE_KIND_ZIP = "zip"

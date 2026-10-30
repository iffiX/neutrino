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
PROTOCOL = 4
# What this side answers as, in the join body and the hello, and what the
# hub answers as in its welcome.
AGENT_ROLE = "agent"
AGENT_HUB_ROLE = "hub"
# What ``software`` reads before the version, on each side of the channel.
AGENT_SOFTWARE_PREFIX = "neutrino_agent/"
AGENT_HUB_SOFTWARE_PREFIX = "neutrino_hub/"

# The largest piece of bytes a container relay moves at once.
AGENT_RELAY_CHUNK_BYTES = 64 * 1024
# How long a ``status`` probe waits for the hub's welcome.
AGENT_PROBE_TIMEOUT_S = 30
# How long a relay waits for the loopback port it dials on this machine.
AGENT_CONNECT_DIAL_TIMEOUT_S = 10
# The address the transport dials for a ``connect`` stream, unless a
# container port is published on one address of its own.
AGENT_CONNECT_LOOPBACK = "127.0.0.1"
# What the ``port`` question is answered with for a port this machine
# does not publish now.
AGENT_CODE_PORT_NOT_PUBLISHED = "port_not_published"
# The protocol a ``connect`` stream that names none carries.
AGENT_CONNECT_TCP = "tcp"
# The AI gateway forward: where the machine's AI tools reach the hub's
# gateway while the state's ``ai_tools`` section is on, and the ``ai``
# entry's id each connection's ``connect`` stream names.
AGENT_AI_FORWARD_HOST = "127.0.0.1"
AGENT_AI_FORWARD_PORT = 8317
AGENT_AI_ENTRY_ID = "ai"
# The relays a container reaches the agent's loopback listeners through:
# one per listener on each Podman bridge on Linux, netavark's ``podmanN``
# and CNI's ``cni-podmanN``, and on the adapter of WSL's NAT network on
# Windows. A relay dials ``127.0.0.1`` on its own port.
AGENT_RELAY_BRIDGE_PATTERN = r"^(cni-)?podman[0-9]+$"
AGENT_RELAY_WSL_ADAPTER_PREFIX = "vEthernet (WSL"
AGENT_RELAY_TARGET_HOST = "127.0.0.1"
AGENT_RELAY_BACKLOG = 64
# How a Linux bridge's addresses are read, once the kernel lists a bridge.
AGENT_RELAY_IP_ADDR_COMMAND = ("ip", "-j", "-4", "addr")
AGENT_RELAY_IP_ADDR_TIMEOUT_S = 10
# The relays' firewall rules: ufw's comment, the prefix of a Windows
# Firewall rule's name before its port, how long the agent goes while it
# holds rules before it reads the firewall again with no relay changed,
# and how long one firewall command may take.
AGENT_RELAY_RULE_COMMENT = "neutrino_agent_relay"
AGENT_RELAY_RULE_PREFIX = "neutrino_agent_relay_"
AGENT_RELAY_FIREWALL_RECHECK_S = 60
AGENT_RELAY_FIREWALL_TIMEOUT_S = 30
# How ufw and firewalld are asked, in the C locale so their answers read
# the same on every machine.
AGENT_RELAY_UFW = "ufw"
AGENT_RELAY_UFW_ACTIVE = "Status: active"
AGENT_RELAY_FIREWALLD = "firewall-cmd"
AGENT_RELAY_FIREWALLD_RUNNING = "running"
# The words of the one rich rule shape the agent writes into firewalld; a
# word ending in ``=`` takes a quoted value, which is read back.
AGENT_RELAY_FIREWALLD_RULE_WORDS = (
    "rule",
    'family="ipv4"',
    "source",
    "address=",
    "destination",
    "address=",
    "port",
    "port=",
    'protocol="tcp"',
    "accept",
)
AGENT_RELAY_COMMAND_LOCALE = "C"
# The codes the channel itself gives: a refusal that named no code, a
# session replaced by a second one for the same binding, the one refusal
# that unbinds, which only the hub's key can say, a binding of 0.5 with no
# hub key, and a frame this build cannot read.
AGENT_CODE_CHANNEL_REFUSED = "channel_refused"
AGENT_CODE_REPLACED = "replaced"
AGENT_CODE_BINDING_UNKNOWN = "binding_unknown"
AGENT_CODE_HUB_KEY_MISSING = "hub_key_missing"
AGENT_CODE_FRAME_UNREADABLE = "frame_unreadable"

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
# The wants under which the software must be there.
AGENT_PRESENT_WANTS = (AGENT_WANT_INSTALLED, AGENT_WANT_STOPPED, AGENT_WANT_RUNNING)
# What the agent reports a module to be, one closed table on every surface:
# five steady states, three in transit, and two shared by every failure.
AGENT_MODULE_STATE_ABSENT = "absent"
AGENT_MODULE_STATE_INSTALLED = "installed"
AGENT_MODULE_STATE_STOPPED = "stopped"
AGENT_MODULE_STATE_RUNNING = "running"
AGENT_MODULE_STATE_INSTALL_FAILED = "install_failed"
AGENT_MODULE_STATE_INSTALLING = "installing"
AGENT_MODULE_STATE_UNINSTALLING = "uninstalling"
AGENT_MODULE_STATE_QUEUED = "queued"
AGENT_MODULE_STATE_FAILED = "failed"
AGENT_MODULE_STATE_UNSUPPORTED = "unsupported"

# The transient unit a self-update runs in. Installing the package restarts
# neutrino_agent.service, so the install must outlive the process that
# started it.
AGENT_UPDATE_UNIT = "neutrino_agent_update"
AGENT_UPDATE_LAUNCH_TIMEOUT_S = 30
# The script a Linux or macOS install runs, written root-only beside the
# agent's state, and how long an install waits for another one to release
# the package manager's lock.
AGENT_UPDATE_SCRIPT_NAME = "update.sh"
AGENT_UPDATE_SCRIPT_MODE = 0o600
AGENT_UPDATE_LOCK_TIMEOUT_S = 300
# How long a launched self-update holds the step lock ``package_manager`` at
# most, while no result tells it ended: the lock's wait and an install's own
# timeout.
AGENT_UPDATE_HOLD_S = 2100
# The name before the kind's extension of the file a Linux or macOS install
# links the received package to beside its script, and installs from: an
# agent that starts clears the packages directory.
AGENT_UPDATE_PACKAGE_STEM = "update"
# What dnf5 says when it refuses at once because another transaction holds
# the rpm lock.
AGENT_UPDATE_DNF_LOCK_TEXT = "rpm transaction lock"
# The Windows Installer holds this mutex while it installs, msiexec answers
# the busy code while another install holds it, and the reboot code when an
# install finished with a restart owed.
AGENT_UPDATE_MSI_MUTEX = "Global\\_MSIExecute"
AGENT_UPDATE_MSI_BUSY_CODE = 1618
AGENT_UPDATE_MSI_REBOOT_CODE = 3010
# The agent's own program as the deb and the rpm install it.
AGENT_LINUX_PROGRAM_PATH = "/usr/bin/nagent"
# Where each package puts the Go programs the agent runs, the transport and
# the SSH server: ``bin/`` in the agent's program directory, under
# ``/opt/neutrino/agent`` on Linux, under the program directory on macOS and
# under Program Files on Windows. The variable names another transport, for
# a checkout.
AGENT_BIN_DIR_LINUX = "/opt/neutrino/agent/bin"
AGENT_BIN_DIR_NAME = "bin"
AGENT_TRANSPORT_BIN_VARIABLE = "NEUTRINO_TRANSPORT_BIN"

# How often a report goes up while nothing changes. Every report carries
# the machine's metrics, which the panel draws live, so this is the rate
# those readings arrive at.
AGENT_REPORT_INTERVAL_S = 5
# Backoff bounds: how long the agent waits before it starts a transport
# that would not start, doubling to a minute.
AGENT_BACKOFF_MIN_S = 5
AGENT_BACKOFF_MAX_S = 60
# The hub's refusal while its Python is away, and the least time between
# two log lines for it.
AGENT_CODE_CONTROL_UNAVAILABLE = "control_unavailable"
AGENT_REFUSAL_LOG_INTERVAL_S = 60
# The name every network the hub serves resolves to the hub's address on that
# network. It heads the addresses a round dials.
AGENT_HUB_NAME = "hub.neutrino.internal"

AGENT_COMMAND_TIMEOUT_S = 900
AGENT_OUTPUT_LIMIT_BYTES = 64 * 1024

# The shell an account's terminal starts when its login shell is not
# usable: the first of these that is.
AGENT_SHELL_FALLBACKS = ("/bin/bash", "/bin/sh")
# The shell an account's terminal starts on Windows when its row names none,
# on a pseudo console.
AGENT_SHELL_WINDOWS_COMMAND = ("powershell.exe", "-NoLogo")
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
# The account a container's shell runs as on Windows, where the agent is
# LocalSystem.
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
# The right a task under an account's login signs in with on Windows, and
# the record under the state root of the accounts the agent granted it.
AGENT_BATCH_LOGON_RIGHT = "SeBatchLogonRight"
AGENT_BATCH_LOGON_RECORD_NAME = "batch_logon.json"
AGENT_WINDOWS_PROGRAM_SUBDIR = ("Neutrino", "agent")
AGENT_WINDOWS_PROGRAM_FILES_DEFAULT = "C:\\Program Files"
AGENT_WINDOWS_BINARY_NAME = "nagent.exe"
# Where Windows is installed when ``SystemRoot`` is unset.
AGENT_WINDOWS_SYSTEM_ROOT_DEFAULT = "C:\\Windows"

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
AGENT_REINSTALL_INSTALLED_CODES = (0, AGENT_UPDATE_MSI_REBOOT_CODE)

# How long a module's live details stand in the report before the engine
# reads them again. The reporter never waits on a read.
AGENT_MODULE_DETAILS_TTL_S = 5.0

# How long a module verb that acts waits for that module's task to end.
AGENT_MODULE_COMMAND_SETTLE_S = 30.0
# How often a step that waits for something outside the agent checks it.
AGENT_MODULE_INSTALL_RECHECK_S = 30.0

# The step locks, in the one order a step takes them in.
AGENT_LOCK_CONTAINERS = "containers"
AGENT_LOCK_PACKAGE_MANAGER = "package_manager"
AGENT_LOCK_SYSTEM_ACCOUNTS = "system_accounts"
AGENT_LOCK_ORDER = (
    AGENT_LOCK_CONTAINERS,
    AGENT_LOCK_PACKAGE_MANAGER,
    AGENT_LOCK_SYSTEM_ACCOUNTS,
)
# How a step takes a lock: beside other shared takers, or alone.
AGENT_LOCK_SHARED = "shared"
AGENT_LOCK_ALONE = "alone"
# The holder a step lock names while the agent's own self-update holds it.
AGENT_LOCK_SELF_UPDATE_HOLDER = "agent"
# How often a module's dnf 5 runs again while another run holds the rpm
# transaction lock, up to ``AGENT_UPDATE_LOCK_TIMEOUT_S``.
AGENT_PACKAGE_LOCK_RETRY_S = 5

# The steps the core plans. A module names its own steps beside them.
AGENT_STEP_PACKAGES = "packages"
AGENT_STEP_ARTIFACT = "artifact"
AGENT_STEP_VERIFY = "verify"
AGENT_STEP_SWITCH = "switch"
AGENT_STEP_CONFIGURE = "configure"
AGENT_STEP_START = "start"
AGENT_STEP_STOP = "stop"
AGENT_STEP_UNINSTALL = "uninstall"
AGENT_STEP_WAIT_CONTAINERS = "wait_containers"
AGENT_STEP_PULL = "pull"
AGENT_STEP_RENDER = "render"
AGENT_STEP_TOOLS = "tools"

# The codes a task's wait names.
AGENT_WAIT_LOCK = "waiting_for_lock"
AGENT_WAIT_PACKAGE_MANAGER = "waiting_for_package_manager"
AGENT_WAIT_MODULE = "waiting_for_module"
AGENT_WAIT_CHECK = "waiting_for_check"
# The start of each line a module's task writes about itself in the agent's
# own log. A module's journal leaves these lines out.
AGENT_TASK_LINE_PREFIX = "{module} task: "

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
# Where each module's last failed step is kept, one root-only file per
# module, so a restart reports it as it was; beside the configured marks.
AGENT_FAILURES_DIR_NAME = "failures"
# Where each ``hub`` module's installed version is kept, one root-only file
# per module with the digest of each artifact it installed; beside the
# configured marks.
AGENT_VERSIONS_DIR_NAME = "versions"
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
# The file SELinux keeps its mode in, there while SELinux is enforcing or
# permissive, and the type systemd runs a program of; a module's unpack under
# the state root is otherwise var_lib_t, which systemd does not run.
AGENT_SELINUX_ENFORCE_PATH = "/sys/fs/selinux/enforce"
AGENT_SELINUX_PROGRAM_TYPE = "bin_t"
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
# code-server, Codeg, SiYuan): how one request's head is read, how bytes are
# relayed, and how long a relayed connection may stay quiet.
AGENT_FORWARD_HEAD_LIMIT_BYTES = 65536
AGENT_FORWARD_CHUNK_BYTES = 65536
AGENT_FORWARD_UPSTREAM_TIMEOUT_S = 10.0
AGENT_FORWARD_IDLE_TIMEOUT_S = 3600.0
# The connections a forwarder's listening socket queues before it accepts them.
AGENT_FORWARD_LISTEN_QUEUE = 128
# How often a forwarder asks whether its page answers yet, and how long a
# refused first start or a failed bind waits before it is tried again.
AGENT_FORWARD_READY_POLL_S = 3.0
AGENT_FORWARD_RETRY_S = 30.0
# The address every forwarder listens on: loopback, where the agent's end of
# a ``connect`` stream reaches it.
AGENT_FORWARD_LISTEN_HOST = "127.0.0.1"
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
# The token's expiry is judged by the hub's time: this machine's clock plus
# the offset the last welcome gave. A move of this machine's clock that
# differs from the monotonic clock's by this many seconds or more, between
# two readings, is the clock being set, and the offset takes it up.
AGENT_HUB_CLOCK_JUMP_S = 2.0
# The install methods a module's recipe names.
AGENT_METHOD_AGENT = "agent"
AGENT_METHOD_BUILTIN = "builtin"
AGENT_METHOD_SYSTEM = "system"
AGENT_METHOD_HUB = "hub"
AGENT_METHOD_CONTAINER = "container"
# The runner of every module of the ``container`` method, and the module
# that runs its containers.
AGENT_CONTAINER_RUNNER = "container"
AGENT_CONTAINERS_MODULE = "podman"
# The kinds of artifact a ``hub`` recipe names: the four kinds unpacked
# under the module's directory, two archives, a macOS disk image whose one
# folder is copied out and a Windows installer whose 7z archive is read, a
# program kept as the publisher's bytes, the two installer packages, the two
# zstd files kept as they came, and an npm package the module's runner
# installs.
AGENT_ARTIFACT_KIND_TAR_GZ = "tar_gz"
AGENT_ARTIFACT_KIND_ZIP = "zip"
AGENT_ARTIFACT_KIND_DMG = "dmg"
AGENT_ARTIFACT_KIND_NSIS = "nsis"
AGENT_ARTIFACT_KIND_BINARY = "binary"
AGENT_ARTIFACT_KIND_MSI = "msi"
AGENT_ARTIFACT_KIND_PKG = "pkg"
AGENT_ARTIFACT_KIND_NPM = "npm"
AGENT_ARTIFACT_ARCHIVE_KINDS = (
    AGENT_ARTIFACT_KIND_TAR_GZ,
    AGENT_ARTIFACT_KIND_ZIP,
    AGENT_ARTIFACT_KIND_DMG,
    AGENT_ARTIFACT_KIND_NSIS,
)
# What a kept artifact's file is named after its artifact, by kind. Podman
# reads an image's compression from the end of its name.
AGENT_ARTIFACT_KEPT_SUFFIXES = {
    AGENT_ARTIFACT_KIND_MSI: ".msi",
    AGENT_ARTIFACT_KIND_PKG: ".pkg",
    "tar_zst": ".tar.zst",
    "raw_zst": ".raw.zst",
}
# A hub artifact's digest is this prefix and the SHA-256 of its bytes in hex.
AGENT_DIGEST_SHA256_PREFIX = "sha256:"
# The probe of a source: how long it waits for an answer, how much of a
# document it reads, and the share of a speed within which two sources go
# to the earlier first byte.
AGENT_SOURCE_PROBE_TIMEOUT_S = 5.0
AGENT_SOURCE_DOCUMENT_LIMIT_BYTES = 4 * 1024 * 1024
AGENT_SOURCE_NEAR_TIE = 0.1
AGENT_SOURCE_HEADERS = {"User-Agent": "neutrino-agent"}
# An image's source: the manifest kinds a registry may answer the request
# for a digest with, the host docker.io's registry answers on, and the
# namespace a docker.io image of one name lives in.
AGENT_SOURCE_MANIFEST_ACCEPT = ", ".join(
    (
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    )
)
AGENT_SOURCE_DOCKER_HUB = "docker.io"
AGENT_SOURCE_DOCKER_REGISTRY = "registry-1.docker.io"
AGENT_SOURCE_DOCKER_LIBRARY = "library"

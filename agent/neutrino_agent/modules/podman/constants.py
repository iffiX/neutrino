"""Fixed values of the container engine module."""

from neutrino_agent.constants import (
    AGENT_LOCK_ALONE,
    AGENT_LOCK_CONTAINERS,
    AGENT_LOCK_PACKAGE_MANAGER,
    AGENT_VAR_DIR,
)

# Podman has no daemon; the API socket stands for the engine.
PODMAN_UNIT = "podman.socket"

# Units name the binary in full: systemd runs them with a minimal PATH.
PODMAN_BINARY = "/usr/bin/podman"

# Where each container's unit lands, on Linux and inside a Podman machine.
PODMAN_UNIT_DIR = "/etc/systemd/system"
PODMAN_UNIT_SUFFIX = ".service"
PODMAN_UNIT_FILE_MODE = 0o644

# Where each container's environment file lands, root only, on Linux and
# inside a Podman machine; the unit's ``podman run`` reads it with
# ``--env-file``.
PODMAN_ENV_DIR = AGENT_VAR_DIR + "/podman/env"
PODMAN_ENV_SUFFIX = ".env"
PODMAN_ENV_FILE_MODE = 0o600
PODMAN_ENV_DIR_MODE = 0o700

# What a unit runs: the cid file it keeps under the runtime directory, the
# seconds ``podman stop`` gives the container, how much longer systemd waits
# for a stop, how long it waits for a start, a first pull among it, and the
# cgroups mode: split on Linux, and enabled inside a Podman machine, whose
# WSL systemd runs under cgroupfs, where split mode finds no pids controller.
PODMAN_CID_FILE = "%t/%N.cid"
PODMAN_STOP_TIMEOUT_S = 10
PODMAN_UNIT_STOP_MARGIN_S = 60
PODMAN_UNIT_START_TIMEOUT_S = 900
# The longest stop timeout a hub container may name.
PODMAN_STOP_TIMEOUT_MAX_S = 3600
# The exit code of a container that ends on the stop's SIGTERM, a clean stop
# for its unit, and the highest exit code there is.
PODMAN_STOP_EXIT_CODE = 143
PODMAN_EXIT_CODE_MAX = 255
PODMAN_CGROUPS = "split"
PODMAN_MACHINE_CGROUPS = "enabled"
# The OCI runtime a Linux unit runs its container with; a Podman machine keeps
# its image's own. Ubuntu 22.04's crun 0.17 answers EPERM to fchmodat2, which
# an image built on glibc 2.39 or later calls.
PODMAN_RUNTIME = "runc"
PODMAN_RM_BINARY = "/bin/rm"

# Where earlier builds wrote a container as a Quadlet ``.container`` file:
# the Linux directory, and the one inside the WSL machine. An apply stops
# and removes each such file that carries the generated marker.
PODMAN_QUADLET_DIRS = ("/etc/containers/systemd", "/usr/share/containers/systemd")
PODMAN_QUADLET_SUFFIX = ".container"

# Where the docker.io mirror list lands. A drop-in, so the distribution's
# own registries.conf stays untouched.
PODMAN_REGISTRIES_CONF_PATH = (
    "/etc/containers/registries.conf.d/99_neutrino_mirrors.conf"
)

# The module's name on the wire, which also names its keeper's task, plist
# and log on Windows and macOS.
PODMAN_MODULE_NAME = "podman"

# The runner a recipe names to run Podman inside a Podman machine.
PODMAN_MACHINE_RUNNER = "podman_machine"

# Containers' own steps beside the core's: the Windows features, the
# restart they owe, and the Podman machine.
PODMAN_STEP_WINDOWS_FEATURES = "windows_features"
PODMAN_STEP_RESTART = "restart"
PODMAN_STEP_MACHINE = "machine"
# The step lock of every step of Containers' own task but the restart. The
# dism step takes the second beside it.
PODMAN_STEP_LOCKS = ((AGENT_LOCK_CONTAINERS, AGENT_LOCK_ALONE),)
PODMAN_FEATURES_LOCKS = ((AGENT_LOCK_PACKAGE_MANAGER, AGENT_LOCK_ALONE),)

# The account's default machine, the one its own ``podman`` reaches.
PODMAN_MACHINE_NAME = "podman-machine-default"

# The machine providers, and the variable that names one to ``podman``.
PODMAN_MACHINE_PROVIDER_WSL = "wsl"
PODMAN_MACHINE_PROVIDER_APPLEHV = "applehv"
PODMAN_MACHINE_PROVIDER_VARIABLE = "CONTAINERS_MACHINE_PROVIDER"

# Under the account's home: the machine's settings file sits in
# ``<provider>/`` under the first, and its key is the second.
PODMAN_MACHINE_SETTINGS_DIR = (".config", "containers", "podman", "machine")
PODMAN_MACHINE_KEY_PATH = (
    ".local",
    "share",
    "containers",
    "podman",
    "machine",
    "machine",
)

# How the agent reads the machine itself: root's API socket in the machine
# through the ssh port the machine forwards to the computer's loopback.
PODMAN_MACHINE_READ_HOST = "127.0.0.1"
PODMAN_MACHINE_SOCKET_PATH = "/run/podman/podman.sock"

# Podman on macOS: its program, its pkg's receipt, and what the pkg and its
# scripts put on the computer.
PODMAN_DARWIN_BINARY = "/opt/podman/bin/podman"
PODMAN_DARWIN_PKG_ID = "com.redhat.podman"
PODMAN_DARWIN_INSTALLED_PATHS = (
    "/opt/podman",
    "/etc/paths.d/podman-pkg",
    "/usr/local/etc/man.d/podman.man.conf",
)
# The computer's logical processors and memory in bytes, one per line.
PODMAN_DARWIN_SYSCTL_COMMAND = ("/usr/sbin/sysctl", "-n", "hw.logicalcpu", "hw.memsize")
# The account's own temporary directory, run as the account: Podman keeps a
# machine's sockets under ``$TMPDIR/podman``.
PODMAN_DARWIN_TEMP_DIR_COMMAND = ("/usr/bin/getconf", "DARWIN_USER_TEMP_DIR")
PODMAN_DARWIN_TEMP_DIR_VARIABLE = "TMPDIR"
PODMAN_DARWIN_COMMAND_TIMEOUT_S = 30

# The machine's memory for a 0 in the Run settings is half the computer's, at
# most the cap. Podman's own 2 GiB serves where the computer's is not read.
PODMAN_MACHINE_DEFAULT_MEMORY_MAX_GIB = 4
PODMAN_MACHINE_FALLBACK_MEMORY_GIB = 2
# Podman's own disk for a 0 in the Run settings.
PODMAN_MACHINE_DEFAULT_DISK_GIB = 100

# The artifact that holds the machine image, and its directory, as the
# manifest names them, and the two kinds it comes in.
PODMAN_MACHINE_IMAGE_ARTIFACT = "image"
PODMAN_MACHINE_IMAGE_KINDS = ("tar_zst", "raw_zst")

# How long the machine's own commands may take: an init unpacks the image,
# about 40 seconds on the lab machine.
PODMAN_MACHINE_INIT_TIMEOUT_S = 900
PODMAN_MACHINE_COMMAND_TIMEOUT_S = 300
# The root script waits for each restart it asks for, a first image pull
# among them.
PODMAN_MACHINE_SCRIPT_TIMEOUT_S = 1800
# How long an apply waits for the machine to answer the read once the keeper
# runs, and how often it asks.
PODMAN_MACHINE_API_WAIT_S = 180
PODMAN_MACHINE_API_POLL_S = 2.0
# How long one reading of the machine is believed within one report.
PODMAN_MACHINE_INFO_TTL_S = 5.0
# How much of a failed command's output a refusal carries.
PODMAN_MACHINE_DETAIL_CHARS = 500
# What the root script prints before each file it changed.
PODMAN_MACHINE_CHANGED_PREFIX = "changed: "
# Bytes in a GiB, for the memory ``podman info`` reports.
PODMAN_GIB = 1024**3

# The keeper: how often it checks the machine, the file it runs, and on
# Windows the socket file a restart can leave behind.
PODMAN_MACHINE_KEEPER_INTERVAL_S = 30
PODMAN_MACHINE_KEEPER_NAMES = {"windows": "keeper.cmd", "darwin": "keeper.sh"}
PODMAN_MACHINE_KEEPER_TITLE = "Podman machine keeper"
PODMAN_MACHINE_WINDOWS_SOCKET = r"%TEMP%\podman\podman-machine-default-api.sock"

# Podman on Windows: its program under ``%ProgramFiles%``, the Windows
# features WSL 2 needs, and the properties Podman's msi is installed with,
# for every account and on WSL.
PODMAN_WINDOWS_BINARY_PARTS = ("Podman", "podman.exe")
PODMAN_WINDOWS_FEATURES = (
    "VirtualMachinePlatform",
    "Microsoft-Windows-Subsystem-Linux",
)
PODMAN_WINDOWS_PODMAN_PROPERTIES = ("ALLUSERS=1", "MACHINE_PROVIDER=wsl")
# The artifact that holds the WSL msi, and the WSL the manifest's ``wsl``
# artifact pins: a WSL installed at this version or newer is kept.
PODMAN_WINDOWS_WSL_ARTIFACT = "wsl"
PODMAN_WINDOWS_WSL_VERSION = "3.0.3"
# The products as Windows Installer lists them under the Uninstall key.
PODMAN_WINDOWS_UNINSTALL_KEY = "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall"
PODMAN_WINDOWS_WSL_PRODUCT = "Windows Subsystem for Linux"
PODMAN_WINDOWS_PODMAN_PRODUCT = "Podman CLI"
# What msiexec exits with for another version of a product already
# installed, and for a product that is not installed.
PODMAN_WINDOWS_OTHER_VERSION_CODE = 1638
PODMAN_WINDOWS_UNKNOWN_PRODUCT_CODE = 1605
# The key Windows holds while servicing waits for a restart.
PODMAN_WINDOWS_RESTART_KEY = (
    "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Component Based Servicing"
    "\\RebootPending"
)
# The reboot mark in the module's directory, holding the boot time of the
# boot that owes the restart; two boot times this close are one boot.
PODMAN_WINDOWS_REBOOT_MARK = "reboot_mark"
PODMAN_WINDOWS_BOOT_SLACK_S = 30
PODMAN_WINDOWS_DISM_TIMEOUT_S = 900
PODMAN_WINDOWS_WSL_TIMEOUT_S = 300
# Under the account's home: its WSL settings, the section and the keys the
# agent writes there, and the WSL disk of its default machine.
PODMAN_WINDOWS_WSLCONFIG = ".wslconfig"
PODMAN_WINDOWS_WSLCONFIG_SECTION = "wsl2"
PODMAN_WINDOWS_DISK_PARTS = (
    ".local",
    "share",
    "containers",
    "podman",
    "machine",
    "wsl",
    "wsldist",
    PODMAN_MACHINE_NAME,
    "ext4.vhdx",
)

# The fields the runner keeps of the last apply, root-only: the declared
# containers' names, the hub containers' names by module, the store's image
# references saved at the last read, and whether Stop stopped the machine.
PODMAN_MACHINE_RECORD_FIELDS = (
    "account",
    "password",
    "cpus",
    "memory_gib",
    "disk_gib",
    "names",
    "hub_names",
    "images",
    "is_stopped",
)
# On Linux root's Podman runs the containers, and its record is root's.
PODMAN_RECORD_FIELDS = ("account", "names", "hub_names")
PODMAN_RECORD_ACCOUNT = "root"

# Every rendered file starts with this, which is how apply tells its own
# files from any a person drops beside them.
PODMAN_GENERATED_MARKER = (
    "# Generated by neutrino. Do not edit; change it on the hub instead."
)

PODMAN_CONTAINER_ACTIONS = ("start", "stop", "restart")

# A hub container: the label naming its module, the start of every name the
# hub keeps for its modules, and the network each module's containers join,
# ``neutrino_<module>``.
PODMAN_MODULE_LABEL = "neutrino.module"
PODMAN_HUB_PREFIX = "neutrino_"
# The network a declared container joins.
PODMAN_DEFAULT_NETWORK = "podman"
# The name every container reaches the machine's listeners at.
PODMAN_HOST_ALIAS = "host.containers.internal"
# How long one pull of a container module's image may take: an image of
# several GB on a slow source.
PODMAN_CONTAINER_PULL_TIMEOUT_S = 3600
# Where a hub container's page port is published on the machine.
PODMAN_PAGE_ADDRESS = "127.0.0.1"
# The file under a container module's directory in the configuration root
# that keeps the loopback port each of its pages is published at.
PODMAN_PAGE_PORTS_NAME = "page_ports.json"
# An image's digest, as a hub container names it.
PODMAN_DIGEST_PATTERN = r"sha256:[0-9a-f]{64}"
# The type of a volume's mount, and the name podman gives an anonymous volume.
PODMAN_VOLUME_MOUNT = "volume"
PODMAN_ANONYMOUS_VOLUME_PATTERN = r"[0-9a-f]{64}"
# Where a container comes from, by the owner rule: the label, then the
# declared names, else a person's own.
PODMAN_SOURCE_HUB = "hub"
PODMAN_SOURCE_DECLARED = "declared"
PODMAN_SOURCE_MANUAL = "manual"
# Where Podman's CNI backend keeps a network, and the cniVersion the
# plugins of Podman 3.4 read.
PODMAN_CNI_DIR = "/etc/cni/net.d"
PODMAN_CNI_SUFFIX = ".conflist"
PODMAN_CNI_VERSION = "0.4.0"

# The verbs a ``command {module: podman}`` names, beside ``validate``.
PODMAN_COMMAND_CONTROL = "control"
PODMAN_COMMAND_JOURNAL = "journal"
PODMAN_JOURNAL_LINES = 200

# The service type of a container's host port, and what each type holds.
PODMAN_SERVICE_AUTO = "auto"
PODMAN_SERVICE_WEB = "web"
PODMAN_SERVICE_PORT = "port"
PODMAN_SERVICE_KINDS = (PODMAN_SERVICE_AUTO, PODMAN_SERVICE_WEB, PODMAN_SERVICE_PORT)
PODMAN_SERVICE_SCHEMES = ("http", "https")
PODMAN_PROTOCOL_TCP = "tcp"
PODMAN_PROTOCOL_UDP = "udp"
PODMAN_PROTOCOLS = (PODMAN_PROTOCOL_TCP, PODMAN_PROTOCOL_UDP)

# What the service probe reports for a published TCP port.
PODMAN_DETECTED_HTTP = "http"
PODMAN_DETECTED_HTTPS = "https"
PODMAN_DETECTED_TCP = "tcp"
# Where a port published on every address is probed.
PODMAN_PROBE_ADDRESS = "127.0.0.1"
# How long the probe waits for a service that speaks first.
PODMAN_PROBE_READ_S = 0.3
# How long each later step waits to connect and for each read.
PODMAN_PROBE_STEP_S = 1.0
# The longest a report waits for the probes it started; a later result is
# kept for the next report.
PODMAN_PROBE_WAIT_S = 1.0
PODMAN_PROBE_REQUEST = b"HEAD / HTTP/1.0\r\n\r\n"
PODMAN_PROBE_REPLY_PREFIX = b"HTTP/"
# Enough of a reply to hold its status code, ``HTTP/1.1 400``.
PODMAN_PROBE_REPLY_BYTES = 12
# The status a web server with TLS on the port answers a plain request with.
PODMAN_PROBE_PLAIN_TO_TLS_STATUS = b"400"

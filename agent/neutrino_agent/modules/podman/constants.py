"""Fixed values of the container engine module."""

# From 4.6 a rendered .container file becomes a unit that can add a host;
# Quadlet reads no file below 4.4 and no key that adds a host below 4.6, so
# below 4.6 the applier writes plain .service units running `podman run`.
PODMAN_QUADLET_VERSION = "4.6"
# Quadlet's AddHost= key comes with 5.3; from 4.6 to 5.2 the host goes
# through PodmanArgs=, and Quadlet refuses a file with a key it lacks.
PODMAN_ADD_HOST_VERSION = "5.3"

# Podman has no daemon; the API socket stands for the engine.
PODMAN_UNIT = "podman.socket"

# Units name the binary in full: systemd runs them with a minimal PATH.
PODMAN_BINARY = "/usr/bin/podman"

# Where a unit rendered for a podman without Quadlet lands.
PODMAN_UNIT_DIR = "/etc/systemd/system"

# Where Quadlet reads declared containers from.
PODMAN_QUADLET_DIR = "/etc/containers/systemd"

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

# The account's default machine, the one its own ``podman`` reaches.
PODMAN_MACHINE_NAME = "podman-machine-default"

# Where Quadlet reads declared containers from inside a machine, by the
# computer's system. In the WSL machine ``/etc/containers`` is a Windows
# folder mounted after systemd's generators run, so the files go on the
# machine's own disk; the applehv machine is Fedora CoreOS, whose ``/usr`` is
# read-only, so they go where Linux has them.
PODMAN_MACHINE_QUADLET_DIRS = {
    "windows": "/usr/share/containers/systemd",
    "darwin": PODMAN_QUADLET_DIR,
}

# Podman 6 mounts the account's containers folder on the machine's
# /etc/containers with this unit, after systemd's generators run. Where the
# Quadlet folder is under that mount, the root script writes the boot unit,
# which reloads systemd and starts multi-user.target's containers after the
# mount, and turns it on with the link.
PODMAN_MACHINE_CONFIG_MOUNT_POINT = "/etc/containers"
PODMAN_MACHINE_CONFIG_MOUNT_UNIT = "/etc/systemd/system/etc-containers.mount"
PODMAN_MACHINE_BOOT_UNIT_NAME = "neutrino_containers.service"
PODMAN_MACHINE_BOOT_UNIT_PATH = "/etc/systemd/system/neutrino_containers.service"
PODMAN_MACHINE_BOOT_UNIT_LINK = (
    "/etc/systemd/system/multi-user.target.wants/neutrino_containers.service"
)

# What every .container file rendered for a machine carries under
# [Container]: the machine runs systemd under cgroupfs, where Quadlet's
# default split mode finds no controllers.
PODMAN_MACHINE_CGROUPS_LINE = "CgroupsMode=enabled"

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

# Podman's own defaults for a 0 in the Run settings.
PODMAN_MACHINE_DEFAULT_MEMORY_GIB = 2
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
# containers' names, and the hub containers' names by module.
PODMAN_MACHINE_RECORD_FIELDS = (
    "account",
    "password",
    "cpus",
    "memory_gib",
    "disk_gib",
    "names",
    "hub_names",
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

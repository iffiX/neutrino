"""Fixed values of the hub_update module."""

from neutrino_hub.utils.constants import UTILS_CONFIG_DIR

# What every release site holds beside a release's files: the file naming
# the newest release, the tag prefix a version is filed under, and each
# release's own digest list, one `<sha256>  <file>` line per file.
HUB_UPDATE_LATEST_NAME = "latest.json"
HUB_UPDATE_TAG_PREFIX = "v"
HUB_UPDATE_CHECKSUMS_NAME = "SHA256SUMS"
# The largest package taken, and how much of it a probe asks for when only
# its size is wanted.
HUB_UPDATE_FETCH_LIMIT_BYTES = 1024 * 1024 * 1024
HUB_UPDATE_SIZE_PROBE_BYTES = 1
# An install reuses a release a check read this recently instead of reading
# the release sites again.
HUB_UPDATE_RELEASE_REUSE_S = 10 * 60

# Under the state root: the packages, the script the unit runs, its log and
# its result. `nhub reset all` clears the directory.
HUB_UPDATE_DIR_NAME = "hub_update"
HUB_UPDATE_STATE_NAME = "state.json"
HUB_UPDATE_SCRIPT_NAME = "update.sh"
HUB_UPDATE_LOG_NAME = "update.log"
HUB_UPDATE_STATE_MODE = 0o600
HUB_UPDATE_SCRIPT_MODE = 0o700
# Readable by apt's own download account, or every install logs a warning.
HUB_UPDATE_PACKAGE_MODE = 0o644
HUB_UPDATE_DIR_MODE = 0o755

# The package lands under the state root and unpacks under the static root;
# dpkg lays the new tree beside the old one before it renames, so the unpacked
# size is counted at this multiple of the compressed file.
HUB_UPDATE_UNPACK_MULTIPLE = 3

# The transient unit the install runs in, away from the panel it restarts.
HUB_UPDATE_UNIT = "neutrino_hub_update"
HUB_UPDATE_LAUNCH_TIMEOUT_S = 30
# The unit's memory ceiling. It bounds the page cache the unpack fills, so a
# box short of memory keeps every other process's pages, PID 1's among them,
# instead of reading them back from behind the unpack's writes. The ceiling
# must clear what the package manager itself holds: dpkg-deb decodes xz with
# one thread here, since each further thread costs it a block of memory.
HUB_UPDATE_UNIT_MEMORY_HIGH = "384M"
HUB_UPDATE_UNIT_ENVIRONMENT = (
    "DEBIAN_FRONTEND=noninteractive",
    "DPKG_DEB_THREADS_MAX=1",
)
# Below this much available memory the unit stops these units before the
# package unpacks, and starts them again once the install is done.
HUB_UPDATE_LOW_MEMORY_BYTES = 300 * 1024 * 1024
HUB_UPDATE_SHED_UNITS = ("neutrino_hub_web", "neutrino_hub_cliproxyapi")
HUB_UPDATE_MEMINFO_PATH = "/proc/meminfo"
# What says this machine has an agent of its own to reinstall.
HUB_UPDATE_AGENT_COMMAND = "nagent"
# What the gate holds for: the panel, and whichever of these was running when
# the install was staged.
HUB_UPDATE_PANEL_UNIT = "neutrino_hub_web"
HUB_UPDATE_GATE_UNITS = ("neutrino_hub_router", "neutrino_hub_dnsmasq")
HUB_UPDATE_HEALTH_PATH = "/api/hub/display"
# What the gate reads to reach the panel: its settings, which name the scheme
# tried first, the other one second, and the authority an HTTPS panel's
# certificate is signed by.
HUB_UPDATE_PANEL_SETTINGS_PATH = UTILS_CONFIG_DIR / "web" / "settings.json"
HUB_UPDATE_PANEL_AUTHORITY_PATH = (
    UTILS_CONFIG_DIR / "web" / "panel_tls" / "authority.pem"
)
HUB_UPDATE_GATE_TIMEOUT_S = 180
HUB_UPDATE_GATE_POLL_S = 2
HUB_UPDATE_OUTPUT_LIMIT_BYTES = 4 * 1024
# The package manager waits this long for another install to release its lock.
HUB_UPDATE_LOCK_TIMEOUT_S = 300
# The file pacman holds while it runs, which it does not wait for itself.
HUB_UPDATE_PACMAN_LOCK_PATH = "/var/lib/pacman/db.lck"
# What dnf5 says when it refuses at once because another transaction holds
# the rpm lock.
HUB_UPDATE_DNF_LOCK_TEXT = "rpm transaction lock"
# The agent's own update, which the script waits out before it reinstalls the
# machine's agent: a transient unit on Linux, a launchd job on macOS, and on
# Windows any install the Windows Installer is running. The agent is given
# the first span to start it once the panel answers, and the second to end
# it.
HUB_UPDATE_AGENT_UPDATE_UNIT = "neutrino_agent_update"
HUB_UPDATE_AGENT_START_S = 20
HUB_UPDATE_AGENT_WAIT_S = 120
# The Windows Installer holds this mutex while it installs, and msiexec
# answers this code while another install holds it.
HUB_UPDATE_MSI_MUTEX = "Global\\_MSIExecute"
HUB_UPDATE_MSI_BUSY_CODE = 1618
# A record written this recently is never taken for an interrupted run: the
# unit, job or process that writes it next may not be running yet.
HUB_UPDATE_SETTLE_GRACE_S = 30
# How long after it ends an update is still shown before anybody signs in.
HUB_UPDATE_DISPLAY_WINDOW_S = 30 * 60

# macOS and Windows: the package family each installs, and how the install
# runs there. On macOS the script is a launchd job of the unit's name, given
# to `launchctl submit`, which removes itself when it ends; on Windows it is a
# PowerShell started apart from the service, whose process id the hub writes
# beside the state file.
HUB_UPDATE_FAMILY_OF_OS = {"darwin": "pkg", "windows": "msi"}
HUB_UPDATE_SCRIPT_NAME_WINDOWS = "update.ps1"
HUB_UPDATE_PID_NAME = "update.pid"
HUB_UPDATE_JOB_DARWIN = f"system/{HUB_UPDATE_UNIT}"
# CREATE_NO_WINDOW with CREATE_BREAKAWAY_FROM_JOB, then CREATE_NO_WINDOW
# alone for a job that refuses breakaway. A PowerShell started with
# DETACHED_PROCESS exits at once without running its script.
HUB_UPDATE_CREATION_FLAGS_WINDOWS = (0x08000000 | 0x01000000, 0x08000000)
# The one service the package registers, and the commands the gate and the
# agent's reinstall run.
HUB_UPDATE_SERVICE_DARWIN = "system/com.neutrino.hub"
HUB_UPDATE_PLIST_DARWIN = "/Library/LaunchDaemons/com.neutrino.hub.plist"
HUB_UPDATE_SERVICE_WINDOWS = "neutrino_hub"
HUB_UPDATE_NHUB_DARWIN = "/usr/local/bin/nhub"
HUB_UPDATE_NHUB_NAME_WINDOWS = "nhub.exe"
HUB_UPDATE_AGENT_COMMAND_DARWIN = "/usr/local/bin/nagent"
HUB_UPDATE_AGENT_COMMAND_WINDOWS = ("Neutrino", "agent", "nagent.exe")
HUB_UPDATE_PROGRAM_FILES_DEFAULT = "C:\\Program Files"
# The agent package the new hub's package seeds into the cache, by family.
HUB_UPDATE_AGENT_PATTERNS = {
    "pkg": "neutrino-agent-{version}-macos-*.pkg",
    "msi": "neutrino-agent-{version}-windows-*.msi",
}
# What msiexec answers for a finished install, with and without a reboot
# owed.
HUB_UPDATE_MSI_INSTALLED_CODES = (0, 3010)

# The task the panel streams while the package is staged.
HUB_UPDATE_TASK_LABEL = "hub_update"

# The record's steps: the lines a person reads, the same on every system.
# The staging writes the download lines, the hand-over the first line here,
# the script the second before it waits for pacman's lock, and it ends every
# run with the third.
HUB_UPDATE_STEP_INSTALLING = "installing; the panel restarts now"
HUB_UPDATE_STEP_WAITING = "waiting for the package manager"
HUB_UPDATE_STEP_DONE = "done"

# Where an update stands, as the state file records it.
HUB_UPDATE_STAGE_PREPARING = "preparing"
HUB_UPDATE_STAGE_INSTALLING = "installing"
HUB_UPDATE_STAGE_INSTALLED = "installed"
HUB_UPDATE_STAGE_ROLLING_BACK = "rolling_back"
HUB_UPDATE_STAGE_ROLLED_BACK = "rolled_back"
HUB_UPDATE_STAGE_FAILED = "failed"
HUB_UPDATE_STAGES = (
    HUB_UPDATE_STAGE_PREPARING,
    HUB_UPDATE_STAGE_INSTALLING,
    HUB_UPDATE_STAGE_INSTALLED,
    HUB_UPDATE_STAGE_ROLLING_BACK,
    HUB_UPDATE_STAGE_ROLLED_BACK,
    HUB_UPDATE_STAGE_FAILED,
)
HUB_UPDATE_STAGES_IN_UNIT = (
    HUB_UPDATE_STAGE_INSTALLING,
    HUB_UPDATE_STAGE_ROLLING_BACK,
)
HUB_UPDATE_STAGES_SETTLED = (
    HUB_UPDATE_STAGE_INSTALLED,
    HUB_UPDATE_STAGE_ROLLED_BACK,
    HUB_UPDATE_STAGE_FAILED,
)

# Why the target version was given up on: the first failure, whatever the
# rollback did after it. Each is worded in the frontend's code catalog.
HUB_UPDATE_REASON_SPACE_SHORT = "disk_space_short"
HUB_UPDATE_REASON_DOWNLOAD_FAILED = "download_failed"
HUB_UPDATE_REASON_PACKAGE_FETCH_FAILED = "package_fetch_failed"
HUB_UPDATE_REASON_PACKAGE_NAME_MISMATCH = "package_name_mismatch"
HUB_UPDATE_REASON_PACKAGE_MISSING = "package_missing"
HUB_UPDATE_REASON_LAUNCH_FAILED = "update_launch_failed"
HUB_UPDATE_REASON_INSTALL_FAILED = "package_install_failed"
HUB_UPDATE_REASON_GATE_FAILED = "health_gate_failed"
HUB_UPDATE_REASON_INTERRUPTED = "update_interrupted"

# How the newest release stands to the version running.
HUB_UPDATE_RELATION_CURRENT = "current"
HUB_UPDATE_RELATION_NEWER = "newer"
HUB_UPDATE_RELATION_MAJOR = "major"

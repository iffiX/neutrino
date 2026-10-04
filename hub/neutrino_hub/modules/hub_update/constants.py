"""Fixed values of the hub_update module."""

from neutrino_hub.utils.constants import UTILS_CONFIG_DIR

# Where the hub's own releases are published, and how a release is asked
# for, by edition: GitHub's API for ``intl``, Gitee's for ``cn``. An edition
# reads its own edition's releases and no other.
HUB_UPDATE_REPOSITORY = "iffiX/neutrino"
HUB_UPDATE_LATEST_URLS = {
    "intl": "https://api.github.com/repos/{repository}/releases/latest",
    "cn": "https://gitee.com/api/v5/repos/{repository}/releases/latest",
}
HUB_UPDATE_TAG_URLS = {
    "intl": "https://api.github.com/repos/{repository}/releases/tags/{tag}",
    "cn": "https://gitee.com/api/v5/repos/{repository}/releases/tags/{tag}",
}
# A release's own page, for an edition whose API names none.
HUB_UPDATE_PAGE_URLS = {
    "intl": "https://github.com/{repository}/releases/tag/{tag}",
    "cn": "https://gitee.com/{repository}/releases/tag/{tag}",
}
HUB_UPDATE_TAG_PREFIX = "v"
# The release's own digest list, one `<sha256>  <file>` line per asset.
HUB_UPDATE_CHECKSUMS_NAME = "SHA256SUMS"
# GitHub's API answers nothing without a User-Agent.
HUB_UPDATE_HEADERS = {
    "User-Agent": "neutrino-hub",
    "Accept": "application/vnd.github+json",
}
HUB_UPDATE_FETCH_TIMEOUT_S = 600
HUB_UPDATE_FETCH_LIMIT_BYTES = 1024 * 1024 * 1024

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

# macOS and Windows: the package family each installs, and how the install
# runs there. On macOS the script is a launchd job of the unit's name, given
# to `launchctl submit`; on Windows it is a PowerShell started detached from
# the service, which writes its process id beside the state file.
HUB_UPDATE_FAMILY_OF_OS = {"darwin": "pkg", "windows": "msi"}
HUB_UPDATE_SCRIPT_NAME_WINDOWS = "update.ps1"
HUB_UPDATE_PID_NAME = "update.pid"
HUB_UPDATE_JOB_DARWIN = f"system/{HUB_UPDATE_UNIT}"
# DETACHED_PROCESS with CREATE_BREAKAWAY_FROM_JOB, then DETACHED_PROCESS
# alone for a job that refuses breakaway.
HUB_UPDATE_CREATION_FLAGS_WINDOWS = (0x00000008 | 0x01000000, 0x00000008)
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
HUB_UPDATE_REASON_PACKAGE_FETCH_FAILED = "package_fetch_failed"
HUB_UPDATE_REASON_PACKAGE_SHA256_MISMATCH = "package_sha256_mismatch"
HUB_UPDATE_REASON_PACKAGE_NAME_MISMATCH = "package_name_mismatch"
HUB_UPDATE_REASON_PACKAGE_MISSING = "package_missing"
HUB_UPDATE_REASON_ROLLBACK_FETCH_FAILED = "rollback_fetch_failed"
HUB_UPDATE_REASON_LAUNCH_FAILED = "update_launch_failed"
HUB_UPDATE_REASON_INSTALL_FAILED = "package_install_failed"
HUB_UPDATE_REASON_GATE_FAILED = "health_gate_failed"
HUB_UPDATE_REASON_INTERRUPTED = "update_interrupted"

# Why GitHub gave no release, one code each so the panel can say which. The
# last is a GitHub that answered with something that is not a release.
HUB_UPDATE_ERROR_RELEASE_DNS = "release_dns_failed"
HUB_UPDATE_ERROR_RELEASE_TIMEOUT = "release_timed_out"
HUB_UPDATE_ERROR_RELEASE_REFUSED = "release_refused"
HUB_UPDATE_ERROR_RELEASE_HTTP = "release_http_error"
HUB_UPDATE_ERROR_RELEASE_UNREACHABLE = "release_unreachable"

# How the newest release stands to the version running.
HUB_UPDATE_RELATION_CURRENT = "current"
HUB_UPDATE_RELATION_NEWER = "newer"
HUB_UPDATE_RELATION_MAJOR = "major"

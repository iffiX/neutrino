"""Fixed values of the agent.

Anything an operator changes lives in ``/etc/neutrino/agent/agent.json``; this
file holds only what is wired into the protocol.
"""

# The hub and the agent share one configuration root with a directory each,
# so a machine running both has one place to look and one place to back up.
AGENT_CONFIG_PATH = "/etc/neutrino/agent/agent.json"

# How many heartbeats in a row the hub may reject — a refused token, a
# certificate off the pin, an agent newer than the hub — before the agent
# drops its binding. One counter for every kind. More than one, so a hub
# caught mid-restore does not shed its whole fleet over a moment's
# inconsistency.
AGENT_REFUSALS_BEFORE_UNBIND = 3

AGENT_SERVICE_NAME = "neutrino_agent.service"

# The shape of what crosses the hub channel. Bumped on any wire change, so
# a hub upgrade that changed the shapes tells a same-version agent to
# reinstall instead of feeding it replies it cannot read.
AGENT_WIRE_GENERATION = 3

AGENT_HEARTBEAT_PATH = "/api/agent/heartbeat"
AGENT_RESULT_PATH = "/api/agent/result"
AGENT_LEAVE_PATH = "/api/agent/leave"
AGENT_PACKAGE_PATH = "/api/agent/package"
# This machine never fetches a module from the internet: the hub's cache did
# that once for every machine of this platform, and an order says which
# artifact to ask it for.
AGENT_MODULE_PACKAGE_PATH = "/api/agent/module_package"

# How much of a failed order's output travels up. Enough to read the package
# manager's own complaint, bounded so a verbose failure cannot fill a beat.
AGENT_MODULE_OUTPUT_LIMIT_BYTES = 16 * 1024

# The transient unit a self-update runs in. Installing the package restarts
# neutrino_agent.service, so the install must outlive the process that
# started it.
AGENT_UPDATE_UNIT = "neutrino_agent_update"
AGENT_UPDATE_LAUNCH_TIMEOUT_S = 30

AGENT_HEARTBEAT_INTERVAL_S = 5
AGENT_REQUEST_TIMEOUT_S = 10
# Backoff bounds used when the gateway is unreachable. Starting at one interval
# and doubling to a minute keeps a rebooting gateway from being hammered while
# still reconnecting promptly once it returns.
AGENT_BACKOFF_MIN_S = 5
AGENT_BACKOFF_MAX_S = 60

AGENT_COMMAND_TIMEOUT_S = 900
AGENT_OUTPUT_LIMIT_BYTES = 64 * 1024

# How long a stepped-down account command may take.
AGENT_STEP_DOWN_TIMEOUT_S = 120

# The local control channel: a socket any local account may connect to,
# whose peer identity the kernel reports, and a loopback page unlocked by
# tokens minted over that socket.
AGENT_CONTROL_SOCKET_PATH = "/run/neutrino_agent/agent.sock"
AGENT_CONTROL_SOCKET_PATH_DARWIN = "/var/run/neutrino_agent/agent.sock"
AGENT_CONTROL_PAGE_HOST = "127.0.0.1"
AGENT_CONTROL_PAGE_PORT = 8765
AGENT_CONTROL_PAGE_ORIGIN = (
    f"http://{AGENT_CONTROL_PAGE_HOST}:{AGENT_CONTROL_PAGE_PORT}"
)
AGENT_CONTROL_REQUEST_TIMEOUT_S = 5

# The page's own polling is a token's pulse. A token whose pulse has stopped
# for this long is expired, which is how a closed window ends its session.
AGENT_CONTROL_TOKEN_IDLE_TTL_S = 10
# How often a waiting `nagent ui` asks whether its token is still alive.
AGENT_UI_WATCH_INTERVAL_S = 2

# Where the machine keeps its service choices — AI switching targets and
# mount records. Machine state: it survives a hub restore and appears in no
# hub backup. Mount passwords never enter it; each mount record has its own
# credentials file under the directory beside it.
AGENT_SERVICE_STORE_PATH = "/etc/neutrino/agent/services.json"
AGENT_MOUNT_CREDENTIALS_DIR = "/etc/neutrino/agent/mount_credentials"

# How often enabled mount records that are not attached are remounted, which
# is also what brings them back after a reboot.
AGENT_MOUNT_RECHECK_INTERVAL_S = 60

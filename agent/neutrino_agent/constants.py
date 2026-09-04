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

AGENT_HEARTBEAT_PATH = "/api/agent/heartbeat"
AGENT_RESULT_PATH = "/api/agent/result"
AGENT_LEAVE_PATH = "/api/agent/leave"
AGENT_PACKAGE_PATH = "/api/agent/package"

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

# Where the AI service keeps its per-account switching state. Machine state:
# it survives a hub restore and appears in no hub backup.
AGENT_AI_STORE_PATH = "/etc/neutrino/agent/ai_service.json"

TODESK_DOWNLOAD_URL = "https://dl.todesk.com/linux/todesk-v4.7.2.0-amd64.deb"
ANYDESK_DOWNLOAD_URL = "https://download.anydesk.com/linux/anydesk_6.3.2-1_amd64.deb"

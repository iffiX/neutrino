"""Fixed values of the agent.

Anything an operator changes lives in ``/etc/neutrino_agent/agent.json``,
written by ``install.sh``; this file holds only what is wired into the protocol.
"""

AGENT_CONFIG_PATH = "/etc/neutrino_agent/agent.json"
AGENT_INSTALL_DIR = "/opt/neutrino_agent"
AGENT_SERVICE_NAME = "neutrino_agent.service"

AGENT_HEARTBEAT_PATH = "/api/agent/heartbeat"
AGENT_RESULT_PATH = "/api/agent/result"
AGENT_LEAVE_PATH = "/api/agent/leave"

AGENT_HEARTBEAT_INTERVAL_S = 5
AGENT_REQUEST_TIMEOUT_S = 10
# Backoff bounds used when the gateway is unreachable. Starting at one interval
# and doubling to a minute keeps a rebooting gateway from being hammered while
# still reconnecting promptly once it returns.
AGENT_BACKOFF_MIN_S = 5
AGENT_BACKOFF_MAX_S = 60

AGENT_COMMAND_TIMEOUT_S = 900
AGENT_OUTPUT_LIMIT_BYTES = 64 * 1024

TODESK_DOWNLOAD_URL = "https://dl.todesk.com/linux/todesk-v4.7.2.0-amd64.deb"
ANYDESK_DOWNLOAD_URL = "https://download.anydesk.com/linux/anydesk_6.3.2-1_amd64.deb"

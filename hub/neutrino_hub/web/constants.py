"""Fixed values of the web layer."""

from neutrino_hub.utils.constants import (
    UTILS_CONFIG_DIR,
    UTILS_DATA_DIR,
    UTILS_LOG_ROOT,
    UTILS_RUNTIME_ROOT,
)

WEB_FRONTEND_DIST_DIR = UTILS_DATA_DIR / "frontend"
WEB_SESSION_COOKIE = "neutrino_session"

# What the panel listens on until somebody says otherwise. One value: setup
# offers it, the unit serves on it, and an enrollment link points a device at
# it, and three copies of it is how a device ends up sent to the wrong port.
WEB_DEFAULT_LISTEN_PORT = 8080

# The agent channel: the /api/agent routes on their own TLS port, pinned by
# the fingerprint every enrollment link carries.
WEB_DEFAULT_AGENT_LISTEN_PORT = 8443
WEB_AGENT_TLS_DIR = UTILS_CONFIG_DIR / "web" / "agent_tls"
WEB_AGENT_TLS_CERT_PATH = WEB_AGENT_TLS_DIR / "certificate.pem"
WEB_AGENT_TLS_KEY_PATH = WEB_AGENT_TLS_DIR / "key.pem"
WEB_AGENT_TLS_SUBJECT = "neutrino-hub"
# Verification is the pinned fingerprint, not the validity window, so the
# certificate simply has to outlive the box.
WEB_AGENT_TLS_VALIDITY_DAYS = 3650
# What a listener may be moved to. Port 0 asks the kernel to choose, which is
# not an answer anybody can then type into a browser.
WEB_PORT_MIN = 1
WEB_PORT_MAX = 65535
# How long the answer gets to reach the browser before the process serving it
# is restarted onto the new port.
WEB_RESTART_DELAY_S = 0.5

# Password hashing. scrypt comes from the standard library, so the appliance
# needs no native crypto dependency to store an admin password safely.
WEB_SCRYPT_SALT_BYTES = 16
WEB_SCRYPT_COST = 2**15
WEB_SCRYPT_BLOCK_SIZE = 8
WEB_SCRYPT_PARALLELISM = 1
WEB_SCRYPT_KEY_BYTES = 32
# OpenSSL refuses a derivation that needs more than its default 32 MiB, and the
# cost above needs exactly that much, so the limit is raised explicitly.
WEB_SCRYPT_MAX_MEMORY_BYTES = 64 * 1024 * 1024

# Login throttling: a personal appliance needs no more than a slow trickle of
# attempts, and this keeps a LAN-side brute force pointless.
WEB_LOGIN_ATTEMPT_LIMIT = 5
# After the free failures are spent, each further failed attempt locks login
# for the next step of this ladder, topping out at a day.
WEB_LOGIN_LOCKOUT_STEPS_S = (30, 60, 300, 3600, 86400)
# The lockout lives in a root-owned file on tmpfs, so it survives a panel
# restart but not a reboot — and `nhub unlock` deletes the file.
WEB_LOGIN_LOCKOUT_STATE_PATH = UTILS_RUNTIME_ROOT / "login_lockout.json"

WEB_STATS_PUSH_INTERVAL_S = 2.0
WEB_DNS_LOG_PATH = UTILS_LOG_ROOT / "dnsmasq.log"

# --- the wizard in a browser ---
# The token the terminal prints and the browser carries. It is the whole of
# the access control: this serves before there is a password to ask for.
WEB_SETUP_TOKEN_BYTES = 24
# Where a run has got to.
WEB_SETUP_STATE_ASKING = "asking"
WEB_SETUP_STATE_REJECTED = "rejected"
WEB_SETUP_STATE_RUNNING = "running"
WEB_SETUP_STATE_DONE = "done"
WEB_SETUP_STATE_FAILED = "failed"
# Where one step has got to, in the words the terminal reports it in. Three
# and no more: a step is running, it succeeded, or it did not. "Already so" is
# a note beside a step that succeeded, not a state of its own — a fourth
# colour in the column makes the run read as though something in it went
# wrong.
WEB_SETUP_STEP_RUNNING = "running"
WEB_SETUP_STEP_DONE = "done"
WEB_SETUP_STEP_FAILED = "failed"
# How long the browser has to appear before the terminal asks again whether
# to keep waiting.
WEB_SETUP_WAIT_S = 0.5
# How long the browser gets to read the last state before the port is given
# back to the panel. Several of its polls, not one: missing this state means
# missing the address the panel will answer at.
WEB_SETUP_GRACE_S = 4.0
# How long the server gets to stop before setup goes on without it.
WEB_SETUP_STOP_TIMEOUT_S = 10.0
# How long it gets to take the port before that is called a failure.
WEB_SETUP_START_TIMEOUT_S = 10.0
WEB_SETUP_START_POLL_S = 0.05

# What the proxy is actually taking, read from the applied ruleset rather than
# from `config/`. One word per answer the status strip can give: the master
# switch is off; on but nothing is sent to it; only the SOCKS ports reach it;
# the forwarded network is diverted; the hub's own traffic is; or both are.
WEB_PROXY_SCOPE_OFF = "off"
WEB_PROXY_SCOPE_UNUSED = "unused"
WEB_PROXY_SCOPE_PORTS = "ports"
WEB_PROXY_SCOPE_LAN = "lan"
WEB_PROXY_SCOPE_HUB = "hub"
WEB_PROXY_SCOPE_LAN_AND_HUB = "lan_and_hub"

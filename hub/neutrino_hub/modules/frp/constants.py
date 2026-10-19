"""Fixed values of the frp module: SakuraFrp and OpenFrp, the two frp ways in."""

from neutrino_hub import HUB_VERSION
from neutrino_hub.utils.constants import carried_program

# The upstream frpc (fatedier/frp, Apache-2.0) every hub package carries.
# packaging/shared/hub_assets.py reads the asset each system and machine takes
# from this release, and its hash, from the table below.
FRP_VERSION = "0.71.1"
FRP_RELEASE_URL = "https://github.com/fatedier/frp/releases/download/v{version}/{asset}"
FRP_ASSETS = {
    ("linux", "amd64"): (
        "frp_0.71.1_linux_amd64.tar.gz",
        "1d9875210972a5d1a62b2dc4c48df45ab0af05d3ca1b5e494a014428259df803",  # scan: allow
    ),
    ("linux", "arm64"): (
        "frp_0.71.1_linux_arm64.tar.gz",
        "8edf590b0c396fa42f9c147121a76af83cfc2002b08f5aef0ea1008c43482019",  # scan: allow
    ),
    ("darwin", "amd64"): (
        "frp_0.71.1_darwin_amd64.tar.gz",
        "8acb59b6fb998cc8d209d1373d90bf70fa5ec3efeb4dfbc7bda6ce3abd78cb45",  # scan: allow
    ),
    ("darwin", "arm64"): (
        "frp_0.71.1_darwin_arm64.tar.gz",
        "d15d0324b99e14619c9aa46e37f6db588c06a09be4bc6f7948890b6b61077842",  # scan: allow
    ),
    ("windows", "amd64"): (
        "frp_0.71.1_windows_amd64.zip",
        "b90074b2b6a1d792a7a40f085ac6d276bcab2d1bc60201f8a86ca53ce65ce821",  # scan: allow
    ),
}
FRP_BINARY_NAME = "frpc"
FRP_BINARY_PATH = carried_program(FRP_BINARY_NAME)

# The two vendors, by the key the configuration, the routes and the
# protocol name them with, and their own spelling.
FRP_SAKURAFRP = "sakurafrp"
FRP_OPENFRP = "openfrp"
FRP_VENDORS = (FRP_SAKURAFRP, FRP_OPENFRP)
FRP_TITLES = {FRP_SAKURAFRP: "SakuraFrp", FRP_OPENFRP: "OpenFrp"}

# The channel's listener for each vendor, on IPv4 loopback alone; frpc
# forwards the vendor's node there.
FRP_SAKURAFRP_LOOPBACK_PORT = 18443
FRP_OPENFRP_LOOPBACK_PORT = 18444
FRP_LOOPBACK_PORTS = {
    FRP_SAKURAFRP: FRP_SAKURAFRP_LOOPBACK_PORT,
    FRP_OPENFRP: FRP_OPENFRP_LOOPBACK_PORT,
}
FRP_LOOPBACK_HOST = "127.0.0.1"

# config/overlay/<vendor>.json, and the binding each credential is sealed
# under.
FRP_CONFIG_NAMES = {
    FRP_SAKURAFRP: "overlay/sakurafrp.json",
    FRP_OPENFRP: "overlay/openfrp.json",
}
FRP_CREDENTIAL_AAD = {
    FRP_SAKURAFRP: b"sakurafrp:credential",
    FRP_OPENFRP: b"openfrp:credential",
}

# Under the state root: one directory per vendor holding the file frpc runs
# from, which holds the account's token.
FRP_FILE_NAME = "frpc.toml"
FRP_DIR_MODE = 0o700
FRP_FILE_MODE = 0o600

# The name the process controller knows each frpc by: a unit of its own on
# Linux, a child of the hub's service on macOS and Windows.
FRP_UNITS = {
    FRP_SAKURAFRP: "neutrino_hub_sakurafrp.service",
    FRP_OPENFRP: "neutrino_hub_openfrp.service",
}

# Every request to either vendor names the hub.
FRP_USER_AGENT = f"Neutrino/{HUB_VERSION}"
FRP_HTTP_TIMEOUT_S = 15.0

# SakuraFrp's API.
FRP_SAKURAFRP_API = "https://api.natfrp.com/v4"
FRP_SAKURAFRP_CONSOLE_URL = "https://www.natfrp.com/tunnel/"
# A node's flag bits: a mainland China node, and one whose visitors first
# authenticate in a browser.
FRP_SAKURAFRP_FLAG_MAINLAND = 1 << 3
FRP_SAKURAFRP_FLAG_FORCED_AUTH = 1 << 8
# A refused key answers HTTP 500 with this code in the body.
FRP_SAKURAFRP_CODE_UNAUTHORIZED = 401

# OpenFrp's API and its remote login.
FRP_OPENFRP_API = "https://api.openfrp.net/frp/api"
FRP_OPENFRP_LOGIN_REQUEST_URL = "https://access.openfrp.net/argoAccess/requestLogin"
FRP_OPENFRP_LOGIN_POLL_URL = "https://access.openfrp.net/argoAccess/pollLogin"
FRP_OPENFRP_CONSOLE_URL = "https://console.openfrp.net/"
FRP_OPENFRP_LOGIN_POLL_S = 5.0
FRP_OPENFRP_LOGIN_TIMEOUT_S = 300.0
# The header the poll's answer carries OpenFrp's public key in, and the one
# any answer may carry a new Authorization in.
FRP_OPENFRP_PUBLIC_KEY_HEADER = "x-request-public-key"
FRP_OPENFRP_AUTHORIZATION_HEADER = "authorization"
# The poll answers this while the person has not confirmed yet.
FRP_OPENFRP_LOGIN_PENDING_STATUS = 204
# A node's classify: its region.
FRP_OPENFRP_REGIONS = {1: "mainland", 2: "hk_mo_tw", 3: "abroad"}

# The login's states.
FRP_LOGIN_IDLE = "idle"
FRP_LOGIN_WAITING = "waiting"
FRP_LOGIN_TIMED_OUT = "timed_out"
FRP_LOGIN_FAILED = "failed"

# A tunnel row's region words.
FRP_REGION_MAINLAND = "mainland"
FRP_REGION_OUTSIDE_MAINLAND = "outside_mainland"

# The tunnel type the hub lists, and frp's own default server port.
FRP_TUNNEL_TYPE = "tcp"
FRP_DEFAULT_SERVER_PORT = 7000

# The latency of a row: a TCP connect from the hub to the node, every node
# at once.
FRP_LATENCY_TIMEOUT_S = 3.0

# The check from outside, on the relay's timing.
FRP_CHECK_FIRST_S = 5.0
FRP_CHECK_INTERVAL_S = 60.0
FRP_CHECK_TIMEOUT_S = 10.0
FRP_TICK_S = 1.0
FRP_LOG_LINES = 40
FRP_CHECK_NO_ANSWER = "no answer at {address}"
FRP_CHECK_FOREIGN = "another certificate at {address}"

# The frp states, network.md "The frp states".
FRP_STATE_DISABLED = "disabled"
FRP_STATE_NOT_SIGNED_IN = "not_signed_in"
FRP_STATE_VAULT_LOCKED = "vault_locked"
FRP_STATE_NO_TUNNEL = "no_tunnel"
FRP_STATE_LOOPBACK_PORT_TAKEN = "loopback_port_taken"
FRP_STATE_CONFIG_FAILED = "config_failed"
FRP_STATE_CONNECTING = "connecting"
FRP_STATE_CONNECTED = "connected"
FRP_STATE_PROXY_REFUSED = "proxy_refused"
FRP_STATE_PORT_CLOSED = "port_closed"
FRP_STATE_LOGIN_FAILED = "login_failed"
FRP_STATE_UNREACHABLE = "unreachable"
# What frpc writes, and what each line means. A proxy the node refused is a
# line holding `start error`, and one it took a line holding
# `start proxy success`; a login the node refused is `login to the server
# failed`, unless the line names a connection that did not happen.
FRP_LINE_START_ERROR = "start error"
FRP_LINE_START_SUCCESS = "start proxy success"
FRP_LINE_LOGIN_FAILED = "login to the server failed"
FRP_LINE_CONNECTION_ERRORS = ("dial tcp", "i/o timeout", "connection refused")

# What an apply changed, as the panel words it.
FRP_CHANGE_STARTED = "frp_started"
FRP_CHANGE_STOPPED = "frp_stopped"

# The coded refusals.
FRP_CODE_FRPC_MISSING = "frpc_missing"
FRP_CODE_CREDENTIAL_REFUSED = "frp_credential_refused"
FRP_CODE_TUNNEL_UNKNOWN = "frp_tunnel_unknown"
FRP_CODE_NOT_SIGNED_IN = "frp_not_signed_in"
FRP_CODE_VENDOR_UNREACHABLE = "frp_vendor_unreachable"
FRP_CODE_CONFIG_UNUSABLE = "frp_config_unusable"

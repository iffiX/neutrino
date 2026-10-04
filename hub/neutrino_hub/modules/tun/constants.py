"""Fixed values of the tun module: the TUN device on macOS and Windows."""

from neutrino_hub.utils.constants import (
    UTILS_GENERATED_DIR,
    UTILS_STATE_ROOT,
    carried_program,
)

# The program that owns the TUN device and hands what enters it to xray. A
# package carries it on macOS and Windows; Linux diverts with nftables.
TUN_BINARY_NAME = "tun2socks"
TUN_BINARY_PATH = carried_program(TUN_BINARY_NAME)
# The name the process controller knows it by.
TUN_SUPERVISED_NAME = "tun2socks"

# The release a package carries, the asset each system and machine takes,
# and its hash. Packaging reads these rather than restating them.
TUN_VERSION = "2.7.0"
TUN_RELEASE_URL = (
    "https://github.com/xjasonlyu/tun2socks/releases/download/v{version}/{asset}"
)
TUN_ASSETS = {
    ("darwin", "amd64"): (
        "tun2socks-darwin-amd64.zip",
        "6e654da8bab9ca1645862f0e251a69980e0966680713011feea7b1e5901b2a95",  # scan: allow
    ),
    ("darwin", "arm64"): (
        "tun2socks-darwin-arm64.zip",
        "7c5ebfe2ffb60ecf6e958cc5bbf3e06e74b8b33575ffbb4ba4f6f785a647f1ad",  # scan: allow
    ),
    ("windows", "amd64"): (
        "tun2socks-windows-amd64.zip",
        "c5d46e9452f6c9cc7c15ab9158d6d6a0169ceecd6bca019ce476b49337d2be43",  # scan: allow
    ),
}
# What the program is called inside each archive.
TUN_ASSET_MEMBER = "tun2socks-{os_name}-{machine}"

# The device tun2socks opens: a utun of a fixed number on macOS, so the
# routes can name it, and a wintun adapter of this name on Windows.
TUN_DEVICE_NAMES = {"darwin": "utun225", "windows": "neutrino_tun"}
# The device's own address, from the range set aside for benchmarking, which
# no served network or overlay uses.
TUN_ADDRESS = "198.18.0.1"  # scan: allow
TUN_PREFIX_LENGTH = 30
# The device's network, which an agent's report never counts as its own.
TUN_NETWORK = f"{TUN_ADDRESS}/{TUN_PREFIX_LENGTH}"
TUN_MTU = 1500
TUN_LOG_LEVEL = "warn"
# The two halves of the address space, sent to the device. Each is longer
# than the uplink's default route, so it wins whatever that route's metric.
TUN_DIVERTED_PREFIXES = ("0.0.0.0/1", "128.0.0.0/1")  # scan: allow
# The metric Windows gives each route the hub adds.
TUN_WINDOWS_ROUTE_METRIC = 1
# What Windows names as the next hop of a route onto an interface.
TUN_WINDOWS_ON_LINK = "0.0.0.0"
# macOS turns IP forwarding on for every interface at once.
TUN_DARWIN_FORWARDING_KEY = "net.inet.ip.forwarding"

# The plan the last routing pass rendered, and what the service applied of
# it: every route added, in order, and the forwarding it turned on.
TUN_PLAN_PATH = UTILS_GENERATED_DIR / "tun_plan.json"
TUN_STATE_PATH = UTILS_STATE_ROOT / "tun_routes.json"

# How long the service waits before it tries again to withdraw routes
# it could not withdraw.
TUN_RETRY_S = 30.0
# How often the service reads again where the overlay engines reach their
# peers, and how long a name among them keeps the address it resolved to.
TUN_ENDPOINT_REFRESH_S = 10.0
TUN_ENDPOINT_NAME_TTL_S = 300.0

# The change and failure codes of the routing pass's TUN step.
TUN_STEP_NAME = "tun"
TUN_CODE_ROUTE_FAILED = "tun_route_failed"

# Adds each route in order. A route that cannot be added is reported and
# the rest are still tried.
TUN_WINDOWS_ROUTE_LOOP = """
$added = @()
$failed = @()
foreach ($route in @($d.routes)) {
  if (-not $route) { continue }
  try {
    New-NetRoute -DestinationPrefix $route.prefix -InterfaceAlias $route.alias `
      -NextHop $route.next_hop -RouteMetric $route.metric `
      -PolicyStore ActiveStore -ErrorAction Stop | Out-Null
    $added += [string]$route.prefix
  } catch {
    $failed += @{prefix = [string]$route.prefix;
      detail = [string]$_.Exception.Message}
  }
}
"""
# Adds routes beside a plan already up.
TUN_WINDOWS_ROUTES_SCRIPT = (
    TUN_WINDOWS_ROUTE_LOOP
    + """@{added = $added; failed = $failed} | ConvertTo-Json -Compress -Depth 4
"""
)
# Gives the adapter its address, turns forwarding on where the document
# asks, then adds each route in order.
TUN_WINDOWS_UP_SCRIPT = (
    """
$present = Get-NetIPAddress -InterfaceAlias $d.alias -IPAddress $d.address `
  -ErrorAction SilentlyContinue
if (-not $present) {
  New-NetIPAddress -InterfaceAlias $d.alias -IPAddress $d.address `
    -PrefixLength $d.prefix_length -PolicyStore ActiveStore | Out-Null
}
$forwarded = @()
foreach ($alias in @($d.forwarding)) {
  if (-not $alias) { continue }
  $held = Get-NetIPInterface -InterfaceAlias $alias -AddressFamily IPv4 `
    -ErrorAction SilentlyContinue
  if ($held -and [string]$held.Forwarding -ne 'Enabled') {
    Set-NetIPInterface -InterfaceAlias $alias -AddressFamily IPv4 `
      -Forwarding Enabled
    $forwarded += [string]$alias
  }
}"""
    + TUN_WINDOWS_ROUTE_LOOP
    + """@{added = $added; forwarded = $forwarded; failed = $failed} |
  ConvertTo-Json -Compress -Depth 4
"""
)
# Removes each route in the order given and turns forwarding off again
# where the hub turned it on. A route already gone is not an error.
TUN_WINDOWS_DOWN_SCRIPT = """
foreach ($route in @($d.routes)) {
  if (-not $route) { continue }
  Remove-NetRoute -DestinationPrefix $route.prefix -InterfaceAlias $route.alias `
    -NextHop $route.next_hop -Confirm:$false -ErrorAction SilentlyContinue
}
foreach ($alias in @($d.forwarding)) {
  if (-not $alias) { continue }
  Set-NetIPInterface -InterfaceAlias $alias -AddressFamily IPv4 `
    -Forwarding Disabled -ErrorAction SilentlyContinue
}
@{withdrawn = $true} | ConvertTo-Json -Compress
"""

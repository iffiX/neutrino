"""Fixed values of the firewall module: the system firewall on macOS and Windows."""

import re

from neutrino_hub.modules.overlay.constants import OVERLAY_EASYTIER, OVERLAY_NETBIRD
from neutrino_hub.utils.constants import UTILS_GENERATED_DIR

# Every Windows rule the hub owns is named by this prefix and its purpose, so
# the rules it made are found by name and nothing else is touched.
FIREWALL_RULE_PREFIX = "neutrino_hub_"
FIREWALL_PURPOSE_PANEL_HTTP = "panel_http"
FIREWALL_PURPOSE_PANEL_HTTPS = "panel_https"
FIREWALL_PURPOSE_AGENT = "agent"
FIREWALL_PURPOSE_AI_GATEWAY = "ai_gateway"
FIREWALL_PURPOSE_SOCKS = "socks_{port}_{protocol}"
FIREWALL_PURPOSE_OVERLAY = "{provider}_{protocol}"
FIREWALL_PROTOCOL_TCP = "TCP"
FIREWALL_PROTOCOL_UDP = "UDP"
# The protocols each overlay's peers knock on its port with.
FIREWALL_OVERLAY_PROTOCOLS = {
    OVERLAY_NETBIRD: (FIREWALL_PROTOCOL_UDP,),
    OVERLAY_EASYTIER: (FIREWALL_PROTOCOL_TCP, FIREWALL_PROTOCOL_UDP),
}
FIREWALL_WINDOWS_DESCRIPTION = "Opened by the Neutrino hub for its own service."
# Where the panel's ports are stored, and the keys of the two that
# web/constants.py names no constant for.
FIREWALL_PANEL_SETTINGS_FILE = "web/settings.json"
FIREWALL_SETTING_LISTEN_PORT = "listen_port"
FIREWALL_SETTING_AGENT_PORT = "agent_listen_port"
# Where the AI gateway's port is stored, and its key.
FIREWALL_GATEWAY_SETTINGS_FILE = "cliproxyapi/cliproxyapi.json"
FIREWALL_SETTING_GATEWAY_PORT = "listen_port"

# What the Windows rules the hub owns are now: name, protocol, port, whether
# each is enabled and the interfaces it is scoped to ("Any" when none).
FIREWALL_WINDOWS_READ_SCRIPT = """
$rules = @(Get-NetFirewallRule -Name ($d.prefix + '*') -ErrorAction SilentlyContinue |
  ForEach-Object {
    $filter = $_ | Get-NetFirewallPortFilter
    $scope = $_ | Get-NetFirewallInterfaceFilter
    @{name = [string]$_.Name; protocol = [string]$filter.Protocol;
      port = [string]$filter.LocalPort;
      is_enabled = ([string]$_.Enabled -eq 'True');
      interfaces = @($scope.InterfaceAlias | ForEach-Object { [string]$_ })}
  })
@{rules = $rules} | ConvertTo-Json -Compress -Depth 4
"""
# Removes, changes and creates the rules the document names, in that order. A
# rule with no interface is kept disabled; one with interfaces is scoped to
# them and enabled.
FIREWALL_WINDOWS_CHANGE_SCRIPT = """
foreach ($name in @($d.remove)) {
  if ($name) { Remove-NetFirewallRule -Name $name -ErrorAction SilentlyContinue }
}
foreach ($rule in @($d.update)) {
  if ($rule) {
    $aliases = @($rule.interfaces)
    if ($aliases.Count -gt 0) {
      Set-NetFirewallRule -Name $rule.name -Protocol $rule.protocol `
        -LocalPort $rule.port -InterfaceAlias $aliases -Enabled True
    } else {
      Set-NetFirewallRule -Name $rule.name -Protocol $rule.protocol `
        -LocalPort $rule.port -Enabled False
    }
  }
}
foreach ($rule in @($d.create)) {
  if ($rule) {
    $aliases = @($rule.interfaces)
    if ($aliases.Count -gt 0) {
      New-NetFirewallRule -Name $rule.name -DisplayName $rule.name `
        -Description $d.description -Direction Inbound -Action Allow `
        -Protocol $rule.protocol -LocalPort $rule.port -Profile Any `
        -InterfaceAlias $aliases | Out-Null
    } else {
      New-NetFirewallRule -Name $rule.name -DisplayName $rule.name `
        -Description $d.description -Direction Inbound -Action Allow `
        -Protocol $rule.protocol -LocalPort $rule.port -Profile Any `
        -Enabled False | Out-Null
    }
  }
}
@{changed = $true} | ConvertTo-Json -Compress
"""

# macOS's application firewall allows programs rather than ports.
FIREWALL_DARWIN_TOOL = "/usr/libexec/ApplicationFirewall/socketfilterfw"
FIREWALL_DARWIN_LIST_LINE = re.compile(r"^\s*\d+\s*:\s*(\S.*?)\s*$")
FIREWALL_DARWIN_ALLOWED = "Allow incoming connections"
FIREWALL_DARWIN_BLOCKED = "Block incoming connections"

# The pf sub-anchor that closes the hub's ports on the interfaces nobody
# exposed. macOS's main ruleset evaluates every ``com.apple/*`` anchor.
FIREWALL_DARWIN_PF_ANCHOR = "com.apple/neutrino_hub"
# Where the anchor's rules are kept between loads: pf forgets them at boot.
FIREWALL_DARWIN_PF_RULES_PATH = UTILS_GENERATED_DIR / "firewall_pf_anchor.conf"
FIREWALL_DARWIN_PF_ENABLED = "Status: Enabled"
FIREWALL_DARWIN_LOOPBACK = "lo0"

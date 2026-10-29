"""Fixed values of the firewall module: the hub's ports in every system's firewall."""

import re

from neutrino_hub.modules.overlay.constants import OVERLAY_EASYTIER, OVERLAY_NETBIRD
from neutrino_hub.utils.constants import UTILS_GENERATED_DIR

# Every Windows rule the hub owns is named by this prefix and its purpose, so
# the rules it made are found by name and nothing else is touched.
FIREWALL_RULE_PREFIX = "neutrino_hub_"
FIREWALL_PURPOSE_PANEL_HTTP = "panel_http"
FIREWALL_PURPOSE_PANEL_HTTPS = "panel_https"
FIREWALL_PURPOSE_AGENT = "agent"
FIREWALL_PURPOSE_DNS = "dns_{protocol}"
FIREWALL_PURPOSE_SOCKS = "socks_{port}_{protocol}"
FIREWALL_PURPOSE_OVERLAY = "{provider}_{protocol}"
# The Windows rule that opens the agent port to every sender on the enabled
# interfaces while Direct is on.
FIREWALL_PURPOSE_DIRECT = "agent_direct"
# The Windows rule that opens the setup wizard's port to every sender before
# setup.
FIREWALL_PURPOSE_SETUP = "setup"
# The Windows rule beside each hub port's that opens it to ``fe80::/64`` on
# the interfaces whose IPv6 segment is exposed, by its purpose's suffix.
FIREWALL_PURPOSE_LINK_SUFFIX = "_link"
FIREWALL_PROTOCOL_TCP = "TCP"
FIREWALL_PROTOCOL_UDP = "UDP"
FIREWALL_DNS_PORT = 53
FIREWALL_DHCP_PORT = 67
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

# The networks each device held at the last firewall pass on macOS and
# Windows, so the half-minute check writes the rules again when a network of
# an exposed segment moved.
FIREWALL_NETWORKS_PATH = UTILS_GENERATED_DIR / "firewall_networks.json"

# What the Windows rules the hub owns are now: name, protocol, port, whether
# each is enabled, the interfaces it is scoped to and the remote addresses it
# allows ("Any" for either when it names none).
FIREWALL_WINDOWS_READ_SCRIPT = """
$rules = @(Get-NetFirewallRule -Name ($d.prefix + '*') -ErrorAction SilentlyContinue |
  ForEach-Object {
    $filter = $_ | Get-NetFirewallPortFilter
    $scope = $_ | Get-NetFirewallInterfaceFilter
    $remote = $_ | Get-NetFirewallAddressFilter
    @{name = [string]$_.Name; protocol = [string]$filter.Protocol;
      port = [string]$filter.LocalPort;
      is_enabled = ([string]$_.Enabled -eq 'True');
      interfaces = @($scope.InterfaceAlias | ForEach-Object { [string]$_ });
      remote_addresses = @($remote.RemoteAddress | ForEach-Object { [string]$_ })}
  })
@{rules = $rules} | ConvertTo-Json -Compress -Depth 4
"""
# Removes the rules the document names, then creates the ones it lists. A
# rule allows the remote addresses it names, or any when it names none, and
# is scoped to the aliases it names that Windows has an adapter by, compared
# without case; a rule that names aliases and is left with none is created
# disabled. Answers, per rule, the aliases left out and the error a refused
# rule raised.
FIREWALL_WINDOWS_CHANGE_SCRIPT = """
$known = @(Get-NetAdapter -IncludeHidden | ForEach-Object { [string]$_.Name })
$dropped = [System.Collections.ArrayList]::new()
$failed = [System.Collections.ArrayList]::new()
function New-HubRule($rule) {
  $wanted = @(@($rule.interfaces) | Where-Object { $_ })
  $aliases = @($wanted | Where-Object { $known -contains $_ })
  $unknown = @($wanted | Where-Object { $known -notcontains $_ })
  if ($unknown.Count -gt 0) {
    [void]$dropped.Add(@{name = [string]$rule.name; interfaces = $unknown})
  }
  $remote = @(@($rule.remote_addresses) | Where-Object { $_ })
  if ($remote.Count -eq 0) { $remote = @('Any') }
  $options = @{Name = $rule.name; DisplayName = $rule.name;
    Description = $d.description; Direction = 'Inbound'; Action = 'Allow';
    Protocol = $rule.protocol; LocalPort = $rule.port; Profile = 'Any';
    RemoteAddress = $remote}
  if ($aliases.Count -gt 0) {
    $options.InterfaceAlias = $aliases
  } elseif ($wanted.Count -gt 0) {
    $options.Enabled = 'False'
  }
  try {
    New-NetFirewallRule @options | Out-Null
  } catch {
    [void]$failed.Add(@{name = [string]$rule.name; error = [string]$_.Exception.Message})
  }
}
foreach ($name in @($d.remove)) {
  if ($name) { Remove-NetFirewallRule -Name $name -ErrorAction SilentlyContinue }
}
foreach ($rule in @($d.create)) {
  if ($rule) { New-HubRule $rule }
}
@{changed = $true; dropped = @($dropped); failed = @($failed)} |
  ConvertTo-Json -Compress -Depth 4
"""
# What Windows reads back for a filter that names nothing.
FIREWALL_WINDOWS_ANY = "any"
# How many times one pass runs the change while an alias is left out or a
# rule is refused, and the wait between two runs.
FIREWALL_WINDOWS_RETRY_COUNT = 5
FIREWALL_WINDOWS_RETRY_WAIT_S = 2.0

# macOS's application firewall allows programs rather than ports.
FIREWALL_DARWIN_TOOL = "/usr/libexec/ApplicationFirewall/socketfilterfw"
FIREWALL_DARWIN_LIST_LINE = re.compile(r"^\s*\d+\s*:\s*(\S.*?)\s*$")
FIREWALL_DARWIN_ALLOWED = "Allow incoming connections"
FIREWALL_DARWIN_BLOCKED = "Block incoming connections"

# The pf sub-anchor that passes the hub's ports from the exposed segments
# and loopback and blocks them from every other sender. macOS's main
# ruleset evaluates every ``com.apple/*`` anchor.
FIREWALL_DARWIN_PF_ANCHOR = "com.apple/neutrino_hub"
# Where the anchor's rules are kept between loads: pf forgets them at boot.
FIREWALL_DARWIN_PF_RULES_PATH = UTILS_GENERATED_DIR / "firewall_pf_anchor.conf"
FIREWALL_DARWIN_PF_ENABLED = "Status: Enabled"
FIREWALL_DARWIN_LOOPBACK = "lo0"
# The anchor's address tables of the exposed segments' networks, by family.
FIREWALL_DARWIN_PF_TABLE_IPV4 = "neutrino_hub_ipv4"
FIREWALL_DARWIN_PF_TABLE_IPV6 = "neutrino_hub_ipv6"

# firewalld, on a Linux hub where it runs.
FIREWALL_FIREWALLD_TOOL = "firewall-cmd"
FIREWALL_FIREWALLD_OFFLINE_TOOL = "firewall-offline-cmd"
FIREWALL_FIREWALLD_RUNNING = "running"
# The priority every rich rule of the hub's carries, which is how its own
# rules are told from the person's. Positive, so the rule sits after the
# zone's own rules and before its target.
FIREWALL_FIREWALLD_PRIORITY = 32123
# One ``key="value"`` of a rich rule as firewall-cmd prints it.
FIREWALL_FIREWALLD_RULE_FIELD = re.compile(r'([a-z-]+)="([^"]*)"')
FIREWALL_FIREWALLD_TIMEOUT_S = 30
# The hub's rich rules in firewalld's runtime as the last pass left them,
# zone to rules, or null when firewalld did not run then; the half-minute
# check compares the runtime with it.
FIREWALL_FIREWALLD_RECORD_PATH = UTILS_GENERATED_DIR / "firewall_firewalld.json"

"""Request and response shapes of the panel API.

These are the contract the frontend's ``api_types.ts`` mirrors field for field,
so a rename here is a rename there.
"""

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """Credentials submitted by the login form."""

    password: str


class SessionView(BaseModel):
    """Whether the caller currently holds a valid session.

    ``lockout_remaining_s`` above zero means login is refused for that many
    more seconds after repeated failures; the login page shows the countdown.
    """

    is_authenticated: bool
    lockout_remaining_s: int = 0
    # This process's start moment. A page that saw one value and now sees
    # another is talking to a restarted panel.
    panel_started_at: str = ""


class DnsServerView(BaseModel):
    """One DNS server the router forwards to."""

    address: str
    port: int = 53


class NodeView(BaseModel):
    """One proxy node as the Nodes tab shows it."""

    id: str
    name: str
    address: str
    protocol: str
    port: int
    is_enabled: bool
    has_reality: bool
    is_alive: bool = False
    delay_ms: int | None = None
    uplink_bytes: int = 0
    downlink_bytes: int = 0


class NodeUpdate(BaseModel):
    """Partial update to one node."""

    is_enabled: bool | None = None
    name: str | None = None


class BalancerSettings(BaseModel):
    """How the balancer picks between nodes."""

    strategy: str
    probe_url: str
    probe_interval_s: int


class NodeListView(BaseModel):
    """The Nodes tab payload."""

    nodes: list[NodeView]
    balancer: BalancerSettings
    is_dirty: bool


class NodeTestResult(BaseModel):
    """Outcome of probing one node."""

    tag: str
    is_alive: bool
    delay_ms: int | None = None


class ApplyResult(BaseModel):
    """Outcome of applying pending configuration changes."""

    is_applied: bool
    message: str


class OutboundTrafficView(BaseModel):
    """Byte counters for one outbound."""

    tag: str
    uplink_bytes: int
    downlink_bytes: int


class NodeProbeView(BaseModel):
    """Latest observatory probe for one node."""

    tag: str
    is_alive: bool
    delay_ms: int | None = None


class StatsFrame(BaseModel):
    """One push on the statistics websocket."""

    timestamp: str
    outbounds: list[OutboundTrafficView] = Field(default_factory=list)
    nodes: list[NodeProbeView] = Field(default_factory=list)
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    uptime_s: int = 0
    wan_address: str | None = None
    total_uplink_bytes: int = 0
    total_downlink_bytes: int = 0
    # What the machine's own uplink is carrying, from its kernel counters.
    # Not the xray totals above: those are the proxy core's traffic since it
    # last started, and the dashboard's bandwidth reading has to be the same
    # interface the history chart is drawn from.
    interface_name: str = ""
    interface_rx_bytes_per_s: int = 0
    interface_tx_bytes_per_s: int = 0
    # Carried on the frame rather than fetched separately: the strip shows it
    # and it is only true as of the moment the frame was taken. One of the
    # WEB_PROXY_SCOPE_* answers — whose traffic the proxy is taking.
    proxy_scope: str = "off"
    # What this machine is set up as, so the strip can say it. Every other
    # chip's meaning follows from it, and the strip used to show none of them
    # a mode to read them by.
    network_mode: str = "server"
    lan_device_count: int = 0
    # Devices whose agent is reporting. Not the neighbour count: a machine
    # this box can see is not a machine it manages, and an SSH login is not
    # an agent.
    agent_device_count: int = 0
    # How traffic is spread, and over how many exits. The strip needs both to
    # answer "where is my traffic going": under leastPing there is one exit to
    # name, and under the others there deliberately is not.
    balancer_strategy: str = "leastPing"
    enabled_node_count: int = 0


class DashboardSummary(BaseModel):
    """The Dashboard tab's initial payload."""

    stats: StatsFrame
    active_exit_tags: list[str]
    dns_query_count: int
    lan_device_count: int


class TrafficSample(BaseModel):
    """Traffic totals for one history bucket."""

    label: str
    received_bytes: int
    sent_bytes: int


class TrafficHistory(BaseModel):
    """A series of history buckets."""

    samples: list[TrafficSample]


class DnsLogEntry(BaseModel):
    """One resolved query from the dnsmasq log."""

    timestamp: str
    domain: str
    client: str
    outbound: str | None = None


class WanInterfaceSettings(BaseModel):
    """How an interface reaches the internet, while its role is ``wan``.

    There is no ranking field. Which uplink carries traffic is worked out from
    what the box can see; ``intent`` says only the part it cannot infer.
    """

    method: str = "dhcp"
    address: str | None = None
    prefix_len: int = 24
    gateway: str | None = None
    intent: str = "auto"
    cloned_mac: str | None = None


class LanInterfaceSettings(BaseModel):
    """The network an interface serves, while its role is ``lan``.

    ``upstream_gateway`` set makes it a side gateway: the box joins an
    existing network, and its way out is that network's real router.
    """

    address: str = ""
    prefix_len: int = 24
    is_dhcp_enabled: bool = True
    dhcp_range_start: str = ""
    dhcp_range_end: str = ""
    dhcp_lease_time: str = "12h"
    upstream_gateway: str | None = None


class WifiInterfaceSettings(BaseModel):
    """Radio settings, used in whichever role a wireless interface has.

    The passphrase of a joined network is absent by design: NetworkManager
    holds it, so the panel never needs a second copy. ``ap_passphrase`` is the
    one the gateway publishes, and is shown because its owner has to be able to
    read it back off the box.
    """

    ssid: str = ""
    ap_ssid: str = ""
    ap_passphrase: str = ""
    ap_band: str = "bg"


class VlanInterfaceSettings(BaseModel):
    """What makes an interface ride on a trunk port.

    ``id`` None marks the trunk's untagged main, shown as ``<parent>.main``.
    """

    parent: str
    id: int | None = None


class InterfaceSettings(BaseModel):
    """One interface's role and the settings for all three of them."""

    name: str
    role: str
    # Read-only here. Which interfaces answer is written as a set, by the
    # panel that shows all of them at once, so a save of one interface takes
    # the stored answer and ignores whatever arrives in the body.
    is_exposed: bool = False
    wan: WanInterfaceSettings = Field(default_factory=WanInterfaceSettings)
    lan: LanInterfaceSettings = Field(default_factory=LanInterfaceSettings)
    wifi: WifiInterfaceSettings = Field(default_factory=WifiInterfaceSettings)
    vlan: VlanInterfaceSettings | None = None


class InterfaceLink(BaseModel):
    """What an interface is actually doing, as opposed to what it is for."""

    name: str
    kind: str = "ethernet"
    is_present: bool = False
    is_up: bool = False
    ipv4_address: str | None = None
    mac_address: str | None = None
    ssid: str | None = None
    signal_percent: int | None = None
    speed_mbps: int | None = None
    gateway: str | None = None
    is_ap_capable: bool = True


class InterfaceView(BaseModel):
    """One row of the Network tab: an interface's config beside its state."""

    settings: InterfaceSettings
    link: InterfaceLink


class PlannedUplinkView(BaseModel):
    """One uplink's place in the gateway's plan for them."""

    name: str
    rank: int
    is_active: bool
    route_metric: int
    reason: str
    speed_mbps: int | None = None


class UpstreamLineView(BaseModel):
    """One path to the internet, and the interfaces that reach it.

    Two interfaces on one line are two doors onto one broadband connection, so
    only the first of them ever carries traffic. Drawing them as one line is
    what makes that self-evident rather than surprising.
    """

    id: str
    gateway: str | None = None
    is_shared: bool = False
    is_carrying: bool = False
    members: list[PlannedUplinkView] = Field(default_factory=list)


class NetworkModeView(BaseModel):
    """One mode, as the Mode panel lists it."""

    key: str
    summary: str
    is_addressing_owned: bool


class NetworkView(BaseModel):
    """The Network tab payload."""

    mode: str
    modes: list[NetworkModeView] = Field(default_factory=list)
    interfaces: list[InterfaceView]
    uplink_policy: str = "failover"
    is_inter_lan_allowed: bool = True
    is_addressing_owned: bool = True
    default_gateway: str | None = None
    lines: list[UpstreamLineView] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class NetworkOptions(BaseModel):
    """The Network tab's settings that belong to no single interface."""

    uplink_policy: str = "failover"
    is_inter_lan_allowed: bool = True
    # Which interfaces answer, by name. A set rather than a flag per request,
    # because the panel shows every interface at once and applying it is one
    # decision about the whole box.
    exposed_interfaces: list[str] = Field(default_factory=list)


class NetworkModeRequest(BaseModel):
    """The mode to become. Nothing else: what each port is for is its own."""

    mode: str


class WifiNetworkView(BaseModel):
    """One network a radio can see."""

    ssid: str
    signal_percent: int
    security: str
    is_active: bool
    is_saved: bool


class WifiScanView(BaseModel):
    """Everything one scan found."""

    networks: list[WifiNetworkView]


class WifiJoinRequest(BaseModel):
    """A network to join, with its passphrase if the gateway lacks one."""

    ssid: str
    passphrase: str | None = None


class SavedNetworkView(BaseModel):
    """One wireless network the box knows how to join.

    The passphrase never comes back out: ``has_secret`` is the whole of what
    the panel is told about it. False means the network was read from a store
    that kept its key somewhere unreadable — a desktop keyring — and the page
    asks for it once.
    """

    ssid: str
    key_mgmt: str
    has_secret: bool
    priority: int
    is_hidden: bool
    source: str


class SavedNetworkListView(BaseModel):
    """Every network the box knows."""

    networks: list[SavedNetworkView]


class NodeCreate(BaseModel):
    """A share link to add as a node.

    One field, because a share link is how every provider hands these out and
    retyping its parts into a form is only a chance to get one wrong.
    """

    link: str


class SocksPortView(BaseModel):
    """One SOCKS5 listener: a port, and which way what arrives there leaves."""

    port: int
    # True goes out through the exit nodes, split the way forwarded traffic
    # is; False leaves straight out the uplink, which is what an application
    # that must appear to come from this network is pointed at.
    is_proxied: bool = False


class ProxySettings(BaseModel):
    """The Proxy tab's switches and the routing lists behind them."""

    is_proxy_enabled: bool = True
    is_direct_fallback_enabled: bool = False
    is_geoip_split_enabled: bool
    direct_domains: list[str]
    direct_ips: list[str]
    is_local_proxy_enabled: bool
    socks_ports: list[SocksPortView] = Field(default_factory=list)
    remote_dns: DnsServerView
    direct_dns: DnsServerView


class KeyView(BaseModel):
    """One SSH key the gateway holds, without its material."""

    id: str
    name: str
    key_type: str
    fingerprint: str
    has_passphrase: bool
    created_at: str
    device_count: int = 0


class KeyListView(BaseModel):
    """The Credentials page's SSH key section."""

    keys: list[KeyView]


class KeyCreate(BaseModel):
    """A pasted key to store under a name."""

    name: str
    private_key: str
    passphrase: str | None = None


class LoginView(BaseModel):
    """One stored login, without its password; None is a bare password."""

    id: str
    name: str
    username: str | None = None
    created_at: str = ""
    device_count: int = 0


class LoginListView(BaseModel):
    """The Credentials page's login section."""

    logins: list[LoginView]


class LoginCreate(BaseModel):
    """A login to store under a name; the password travels one way.

    A null username is a bare password, which is what the form sends.
    """

    name: str
    username: str | None = None
    password: str


class TokenView(BaseModel):
    """One stored token, without its value."""

    id: str
    name: str
    created_at: str = ""
    provider_count: int = 0
    node_count: int = 0


class TokenListView(BaseModel):
    """The Credentials page's token section."""

    tokens: list[TokenView]


class TokenCreate(BaseModel):
    """A token to store under a name; the value travels one way."""

    name: str
    value: str


class AiProviderModelView(BaseModel):
    """One model alias a provider serves: real name in, served alias out."""

    name: str
    alias: str = ""


class AiProviderView(BaseModel):
    """One stored AI provider; its key is a reference into the vault."""

    id: str
    name: str
    kind: str
    base_url: str = ""
    secret_id: str | None = None
    is_enabled: bool = True
    models: list[AiProviderModelView] = Field(default_factory=list)
    created_at: str = ""


class AiProviderListView(BaseModel):
    """The AI page's provider section."""

    providers: list[AiProviderView]


class AiProviderCreate(BaseModel):
    """A provider to store; ``secret_id`` names a vault token, or nothing."""

    name: str
    kind: str
    base_url: str = ""
    secret_id: str | None = None
    models: list[AiProviderModelView] = Field(default_factory=list)


class AiProviderOrderUpdate(BaseModel):
    """The served order being saved: every provider id, in the new order."""

    provider_ids: list[str]


class AiProviderUpdate(BaseModel):
    """Partial update to one provider; ``secret_id`` sent as null clears the
    reference, and left out keeps it."""

    name: str | None = None
    kind: str | None = None
    base_url: str | None = None
    secret_id: str | None = None
    is_enabled: bool | None = None
    models: list[AiProviderModelView] | None = None


class CliproxyApiKeyView(BaseModel):
    """One client key of the AI gateway, shown in full to its owner."""

    id: str
    name: str
    key: str
    created_at: str = ""


class CliproxyApiStatusView(BaseModel):
    """The AI page payload."""

    is_installed: bool
    is_active: bool
    listen_port: int
    client_keys: list[CliproxyApiKeyView] = Field(default_factory=list)
    is_reachable: bool = False
    probe_message: str = ""
    served_models: list[str] = Field(default_factory=list)
    enabled_provider_count: int = 0
    # Whether the stored configuration differs from what the last apply handed
    # the gateway, which is what lights the Providers panel's apply bar.
    is_serving_stale: bool = False
    # The strip's numbers: the current UTC day, tokens as input plus output.
    requests_today: int = 0
    tokens_today: int = 0
    # Signed-in subscription accounts, which serve beside the key providers
    # and are counted separately because nothing applies them.
    account_count: int = 0


class CliproxyApiUsageRates(BaseModel):
    """Requests and tokens per minute, averaged over the last hour."""

    rpm: float = 0.0
    tpm: float = 0.0


class CliproxyApiUsageTotals(BaseModel):
    """One counter set over a range or bucket."""

    requests: int = 0
    failed: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


class CliproxyApiUsageBucket(CliproxyApiUsageTotals):
    """One series bucket: an ISO hour for day range, a date for the rest."""

    bucket: str


class CliproxyApiUsageKey(CliproxyApiUsageTotals):
    """One client key's usage over the range."""

    key_id: str
    name: str
    device_name: str | None = None
    first_seen_at: str = ""
    last_seen_at: str = ""


class CliproxyApiHealthBucket(BaseModel):
    """One hour of a provider's health bar."""

    bucket: str
    requests: int = 0
    failed: int = 0


class CliproxyApiUsageProvider(CliproxyApiUsageTotals):
    """One upstream's usage over the range.

    An upstream is an API-key provider or a subscription account, and the two
    share this shape: ``provider_id`` is the provider's id or the account's
    token file, and ``kind`` the provider's kind or the account's service.
    """

    provider_id: str
    name: str
    kind: str
    is_account: bool = False
    first_seen_at: str = ""
    last_seen_at: str = ""
    health: list[CliproxyApiHealthBucket] = Field(default_factory=list)


class CliproxyApiUsageView(BaseModel):
    """The usage answer: rates, totals, the series, keys and providers."""

    range: str
    generated_at: str
    rates: CliproxyApiUsageRates
    totals: CliproxyApiUsageTotals
    series: list[CliproxyApiUsageBucket] = Field(default_factory=list)
    keys: list[CliproxyApiUsageKey] = Field(default_factory=list)
    providers: list[CliproxyApiUsageProvider] = Field(default_factory=list)


class CliproxyApiJournalView(BaseModel):
    """The AI gateway's journal tail, most recent last."""

    lines: list[str] = Field(default_factory=list)


class CliproxyApiKeyCreate(BaseModel):
    """A client key to generate under a name."""

    name: str


class CliproxyApiSettingsUpdate(BaseModel):
    """The AI gateway's adjustable settings."""

    listen_port: int


class CliproxyApiApplyResult(BaseModel):
    """Outcome of rendering and restarting the AI gateway."""

    message: str


class CliproxyApiAccountView(BaseModel):
    """One subscription account the gateway holds a token file for.

    There is no expiry here because the gateway refreshes its own tokens; what
    it reports instead is whether the account is serving.
    """

    name: str
    provider: str
    label: str = ""
    email: str = ""
    account_type: str = ""
    status: str = ""
    status_message: str = ""
    is_disabled: bool = False
    is_unavailable: bool = False
    failed_count: int = 0
    success_count: int = 0
    created_at: str = ""
    updated_at: str = ""


class CliproxyApiAccountsView(BaseModel):
    """The accounts panel's payload: what is signed in, and what can sign in."""

    accounts: list[CliproxyApiAccountView] = Field(default_factory=list)
    login_kinds: list[str] = Field(default_factory=list)


class CliproxyApiLoginStart(BaseModel):
    """Which flow to begin."""

    kind: str


class CliproxyApiLoginView(BaseModel):
    """A login in progress, and what the person has to do with it.

    ``flow`` is ``device`` where the provider shows a code to approve and the
    gateway finishes on its own, ``redirect`` where the browser is sent to a
    loopback address on the gateway that it cannot reach, and the address bar
    is what comes back through :class:`CliproxyApiLoginCode`.
    """

    state: str
    kind: str
    url: str
    flow: str
    user_code: str = ""
    expires_in: int = 0


class CliproxyApiLoginCode(BaseModel):
    """The code a redirect flow came back with, or the whole address."""

    code: str


class CliproxyApiLoginStateView(BaseModel):
    """Where a login has got to: ``pending``, ``complete`` or ``failed``."""

    state: str
    status: str
    message: str = ""


class DeviceSshConfig(BaseModel):
    """SSH credentials for one device.

    Every credential is a reference: ``key_id`` names a stored key,
    ``password_id`` and ``sudo_password_id`` name vault login objects. No
    secret material passes through this model; ``key_name`` is the resolved
    label for display.
    """

    host: str
    port: int = 22
    username: str
    auth: str = "key"
    key_id: str | None = None
    key_name: str | None = None
    password_id: str | None = None
    sudo_password_id: str | None = None


class DeviceGpuView(BaseModel):
    """One graphics card as the agent reports it."""

    vendor: str = ""
    name: str = ""
    utilization_percent: float | None = None
    memory_used_mb: int | None = None
    memory_total_mb: int | None = None
    temperature_c: float | None = None
    power_w: float | None = None


class DeviceProcessView(BaseModel):
    """One busy process from the agent's latest sample."""

    pid: int = 0
    user: str = ""
    name: str = ""
    cpu_percent: float = 0.0
    memory_percent: float = 0.0


class DeviceClientErrorView(BaseModel):
    """The most recent error an agent reported; the pages do the wording."""

    code: str
    params: dict = Field(default_factory=dict)


class DeviceCommandResultView(BaseModel):
    """How one queued command went, as the agent reported it back."""

    id: str
    exit_code: int
    output: str = ""
    finished_at: str = ""


class DeviceClientInfoView(BaseModel):
    """Agent state and latest metrics for one device."""

    # An agent that completed its handshake and still holds a token. A generated
    # token whose install then failed never reads managed.
    is_managed: bool = False
    # Whether the agent has checked in inside the heartbeat window.
    is_online: bool = False
    version: str | None = None
    # True when the agent's version is not this hub's. The two ship together
    # and are only supported together, so the panel offers an upgrade rather
    # than trying to interoperate.
    is_version_mismatched: bool = False
    last_seen: str | None = None
    # What the agent said it runs on, held in memory from its heartbeats and
    # never stored: None until it beats again after a panel restart.
    platform_os: str | None = None
    platform_arch: str | None = None
    hostname: str | None = None
    cpu_percent: float | None = None
    memory_percent: float | None = None
    disk_percent: float | None = None
    temperature_c: float | None = None
    uptime_s: int | None = None
    load_average: list[float] = Field(default_factory=list)
    cpu_core_percents: list[float] = Field(default_factory=list)
    gpus: list[DeviceGpuView] = Field(default_factory=list)
    processes: list[DeviceProcessView] = Field(default_factory=list)
    last_error: DeviceClientErrorView | None = None
    # The last outcome of each queued command, newest first.
    command_results: list[DeviceCommandResultView] = Field(default_factory=list)


class DeviceView(BaseModel):
    """One LAN device as the Devices tab shows it.

    Reachability and capability are separate questions: ``is_online`` says
    whether the box can currently be reached at all, by any route, while the
    SSH block and the agent say what could be done once it is.
    """

    mac_address: str
    ipv4_address: str
    name: str | None = None
    icon: str | None = None
    vendor: str = ""
    is_online: bool = False
    # Whether the agent has beaten recently. False on a device with no agent,
    # and on one whose agent has gone quiet — which is how a machine that is
    # up but no longer reporting is told apart from one that is off.
    is_agent_online: bool = False
    is_wol_enabled: bool = False
    has_ssh: bool = False
    # Whether this box holds anything about the device — a name, credentials,
    # an agent token. A scan-only row holds nothing, so there is nothing to
    # forget.
    is_stored: bool = False
    ssh: DeviceSshConfig | None = None
    client: DeviceClientInfoView | None = None


class DeviceListView(BaseModel):
    """The Devices tab payload."""

    devices: list[DeviceView]


class DeviceAnnotation(BaseModel):
    """Partial update to one device."""

    name: str | None = None
    icon: str | None = None
    is_wol_enabled: bool | None = None
    ssh: DeviceSshConfig | None = None


class DeviceActionRequest(BaseModel):
    """A long-running action to start on a device."""

    action: str


class DeviceProcessKill(BaseModel):
    """A process to end on a device."""

    pid: int


class DeviceFileEntryView(BaseModel):
    """One name in a device directory listing."""

    name: str
    is_dir: bool = False
    is_link: bool = False
    size_bytes: int = 0
    modified_at: int = 0


class DeviceFileListView(BaseModel):
    """One device directory, resolved and listed."""

    path: str
    entries: list[DeviceFileEntryView] = Field(default_factory=list)


class DeviceFilePath(BaseModel):
    """A remote path to act on."""

    path: str


class DeviceFileRename(BaseModel):
    """A remote path and where to move it."""

    path: str
    new_path: str


class RemoteDesktopStatusView(BaseModel):
    """One remote-desktop product's state on a device.

    Whether it can be put there is a module's business; this is what the
    running product itself knows.
    """

    product: str
    is_installed: bool
    is_running: bool
    # Why the device could not be asked, empty when it was. Without it a
    # machine that is off, a wrong password and a changed host key all read as
    # "not installed", and the panel offers to install what is already there.
    unreachable: str = ""
    session_id: str | None = None
    can_set_password: bool = False


class RemoteDesktopView(BaseModel):
    """Both remote-desktop products' state on a device."""

    anydesk: RemoteDesktopStatusView
    todesk: RemoteDesktopStatusView


class RemoteDesktopPassword(BaseModel):
    """A password to set for unattended access."""

    password: str


class TaskStarted(BaseModel):
    """Handle for streaming a started action's output."""

    task_id: str


class TaskView(BaseModel):
    """One background job of this panel, and what it is doing."""

    id: str
    label: str


class TaskListView(BaseModel):
    """The background jobs still running."""

    tasks: list[TaskView]


class WolResult(BaseModel):
    """Outcome of sending a magic packet."""

    is_sent: bool
    message: str


class ModuleView(BaseModel):
    """One managed systemd unit.

    ``is_core`` is what decides whether the panel offers to stop it. Core units
    are what makes this a gateway rather than a computer, so they get status and
    logs and no off switch.
    """

    name: str
    unit: str
    is_installed: bool
    is_active: bool
    is_enabled: bool
    is_core: bool = True
    # The install machinery: set only for modules the panel can install and
    # remove. A module a machine cannot run says so up front, on the button.
    is_installable: bool = False
    is_machine_supported: bool = True
    unsupported_reason: str | None = None
    install_note: str = ""
    data_description: str = ""


class PublishedServiceView(BaseModel):
    """One entry of the typed service list.

    ``payload`` is the type's own — a url for web, host and port for port,
    endpoint, protocol and models for ai, protocol, host and share for file.
    ``record_id`` names the declared record behind a declared entry; a
    module-declared entry carries None and is read-only. ``detail_code`` is
    what that record's last probe measured, None on one that answered as
    declared and on every module entry.
    """

    id: str
    type: str
    title: str
    payload: dict
    is_healthy: bool | None = None
    source: str
    description: str = ""
    record_id: str | None = None
    detail_code: str | None = None


class DeclaredServiceCreate(BaseModel):
    """A declaration as the form submits it.

    ``kind`` is a service type — web, port or file — mapped onto the stored
    probe kind; the fields a kind does not have are ignored. A ``file``
    declaration left without a port gets 445, and names every share it
    declares on that server.
    """

    name: str
    kind: str
    host: str
    port: int | None = None
    scheme: str | None = None
    path: str | None = None
    shares: list[str] | None = None
    description: str = ""


class ServiceShareListView(BaseModel):
    """What one SMB server exports, administrative shares dropped."""

    shares: list[str] = Field(default_factory=list)


class ServiceListView(BaseModel):
    """The Services tab payload: every published entry."""

    services: list[PublishedServiceView]


class ModuleListView(BaseModel):
    """The Modules tab payload."""

    modules: list[ModuleView]


class ProvisionConsentView(BaseModel):
    """One thing installing would do that the person agrees to first.

    ``code`` says what kind of consequence it is and ``detail`` carries the
    values its sentence needs. The backend writes neither the sentence nor
    the title: wording belongs to the panel, which is what lets it be
    translated.
    """

    code: str
    detail: dict


class ModuleInstallPlanView(BaseModel):
    """What installing a module on this machine would actually do."""

    name: str
    is_consent_needed: bool
    consents: list[ProvisionConsentView]


class ModuleInstallRequest(BaseModel):
    """Whether the person has agreed to what the plan listed.

    False is the ordinary case: a module whose plan asks nothing installs on
    the press that started it.
    """

    is_consented: bool = False


class ModuleUninstallRequest(BaseModel):
    """How much of a module to take away.

    Data is kept unless explicitly surrendered: uninstall-then-install must be
    a round trip by default, and deleting repositories or shared files is a
    decision, never a side effect.
    """

    is_data_kept: bool = True


class JournalView(BaseModel):
    """A unit's journal tail."""

    text: str


class PasswordChange(BaseModel):
    """A password change request."""

    current_password: str
    new_password: str


class PasswordChangeResult(BaseModel):
    """Outcome of a password change."""

    is_changed: bool


class PanelSettings(BaseModel):
    """The panel's own network settings.

    One field, and it is the one nowhere else can hold: every other service
    settles its port in its own tab, and the panel is a service too.
    """

    listen_port: int


class AboutView(BaseModel):
    """Versions and uptime for the Settings tab."""

    xray_version: str
    gateway_version: str
    cliproxyapi_version: str
    python_version: str
    geodata_version: str
    kernel: str
    uptime_s: int


class ClientHeartbeat(BaseModel):
    """A heartbeat posted by a neutrino_agent agent."""

    token: str
    hostname: str
    client_version: str
    # The wire generation the agent was built to; 0 marks a build from
    # before generations existed.
    wire: int = 0
    metrics: dict = Field(default_factory=dict)
    platform: dict = Field(default_factory=dict)
    # The machine's human accounts, the platform's own judgment; root is
    # never listed.
    accounts: list[str] = Field(default_factory=list)
    catalog_hash: str = ""
    # What state each module is in: name to
    # ``{"state", "code", "params", "is_active"}``. What is true, which is
    # the only thing about modules the machine answers for.
    modules: dict = Field(default_factory=dict)
    # Toggles made on the machine's own page. They ask the hub rather than
    # act, so the drawer and the page cannot disagree for longer than a beat.
    module_requests: dict = Field(default_factory=dict)
    # How the orders this machine has finished went: one
    # ``{"id", "state", "code", "params", "output"}`` each.
    module_results: list[dict] = Field(default_factory=list)
    # Which accounts want their AI tools pointed at the gateway.
    ai_targets: dict[str, bool] = Field(default_factory=dict)
    # The most recent error worth showing, as ``{"code", "params"}``.
    last_error: dict | None = None


class ClientCommand(BaseModel):
    """One queued command handed back to an agent."""

    id: str
    action: str
    args: dict = Field(default_factory=dict)


class ClientModuleOrder(BaseModel):
    """One thing the hub is telling a machine to do to one module.

    An order names the module, the action, and how to get the bytes — never
    the bytes themselves, which the machine asks for separately so a beat
    stays a beat.
    """

    id: str
    module: str
    action: str
    # What the machine asks the hub for the bytes by, and what it checks
    # them against. Empty for an action that downloads nothing.
    artifact_key: str = ""
    digest: str = ""
    package_kind: str = ""


class ClientHeartbeatReply(BaseModel):
    """The gateway's answer to a heartbeat.

    ``catalog`` is sent only when the agent's ``catalog_hash`` is stale, so a
    converged fleet is not shipped it on every beat.
    """

    commands: list[ClientCommand] = Field(default_factory=list)
    # What to do now, rather than a state to work out for itself. At most
    # one stands at a time: a machine installs one thing at a time.
    module_orders: list[ClientModuleOrder] = Field(default_factory=list)
    # ``{"modules", "services"}`` under one hash.
    catalog: dict | None = None
    catalog_hash: str = ""
    # ``{account: {"base_url", "api_key", "model"}}`` for the accounts whose
    # AI target is on; the one per-device secret the reply carries.
    ai_accounts: dict = Field(default_factory=dict)
    # The hub's own version, on every reply: an older agent updates itself
    # from it, so a hub restarted with a new release reaches its fleet within
    # one beat.
    hub_version: str = ""


class DeviceEnrollmentRequest(BaseModel):
    """Ask the gateway for a link a machine can join with."""

    name: str = ""
    mac_address: str | None = None


class DeviceEnrollmentView(BaseModel):
    """The link to paste into a machine's own agent page."""

    link: str
    token: str
    expires_in_s: int


class ClientEnroll(BaseModel):
    """A machine introducing itself with an enrollment token."""

    enrollment_token: str
    device_id: str
    hostname: str = ""
    client_version: str = ""
    wire: int = 0
    platform: dict = Field(default_factory=dict)
    # Every MAC the machine's interfaces carry, so an unbound link still
    # lands on the device a scan or an SSH setup already listed.
    mac_addresses: list[str] = Field(default_factory=list)


class ClientEnrollReply(BaseModel):
    """What the gateway hands back once a machine has joined."""

    token: str
    mac_address: str
    hub_version: str = ""


class ClientPackageRequest(BaseModel):
    """An agent asking for the hub's baked package for its family."""

    token: str
    family: str


class ClientModulePackage(BaseModel):
    """An agent asking for the bytes an order named."""

    token: str
    artifact_key: str


class DeviceModuleView(BaseModel):
    """One managed module, as the panel shows it for a device."""

    name: str
    title: str
    description: str = ""
    is_supported: bool = True
    is_enabled: bool = False
    # A platform capability the machine already carries, worded as
    # enable/disable rather than install/uninstall.
    is_builtin: bool = False
    # Whether installing and pointing at the hub are separate steps.
    has_activation: bool = False
    is_activated: bool = False
    is_active: bool = False
    state: str = "unknown"
    # Why the state is what it is, when the agent said; the pages word it.
    code: str = ""
    params: dict = Field(default_factory=dict)


class DeviceModuleListView(BaseModel):
    """Every module a device could run, with its state.

    ``is_agent_online`` is what makes the list readable: every module's
    state comes from the agent, so with no agent answering they are all
    unknown, and a page that cannot say why draws them as "not installed"
    beside a remote desktop it can see running.
    """

    modules: list[DeviceModuleView] = Field(default_factory=list)
    is_agent_managed: bool = False
    is_agent_online: bool = False


class DeviceModuleUpdate(BaseModel):
    """Change what is wanted of one module; absent fields are left alone."""

    is_enabled: bool | None = None
    is_activated: bool | None = None


class DeviceInstallOrderView(BaseModel):
    """One install on a device, as the drawer's install pane shows it."""

    id: str
    module: str
    # The module's own title, so a failure is read beside the thing it was.
    title: str = ""
    action: str
    state: str
    code: str = ""
    params: dict = Field(default_factory=dict)
    # What the failing step printed, so a person reads the vendor's own
    # words rather than only that something went wrong.
    output: str = ""
    asked_at: str = ""
    finished_at: str = ""


class DeviceInstallOutputView(BaseModel):
    """Every install this device has run, newest first."""

    orders: list[DeviceInstallOrderView] = Field(default_factory=list)


class ClientLeave(BaseModel):
    """An agent saying it is leaving; the token is all it needs to prove."""

    token: str


class ClientCommandResult(BaseModel):
    """An agent reporting how a command went."""

    token: str
    id: str
    exit_code: int
    output: str = ""


class SambaShareView(BaseModel):
    """One exported directory, as configured."""

    name: str
    path: str
    comment: str = ""
    is_read_only: bool = False
    valid_users: list[str] = Field(default_factory=list)


class SambaUserView(BaseModel):
    """One share user, with what the box actually holds for it."""

    name: str
    is_present: bool
    has_password: bool


class SambaSettingsView(BaseModel):
    """The Samba tab: configuration plus each user's live state."""

    shares: list[SambaShareView]
    users: list[SambaUserView]


class SambaShareListUpdate(BaseModel):
    """The Shares group being saved."""

    shares: list[SambaShareView]


class SambaUserListUpdate(BaseModel):
    """The Users group being saved: names only, passwords are set apart."""

    users: list[str]


class SambaPasswordUpdate(BaseModel):
    """A new password for one user, which goes to Samba's store and nowhere
    else."""

    password: str = Field(min_length=1, max_length=128)


class SambaSessionView(BaseModel):
    """One live connection to the server."""

    username: str
    hostname: str
    remote_address: str
    shares: list[str] = Field(default_factory=list)


class SambaDiskView(BaseModel):
    """How full one share's filesystem is."""

    share: str
    total_bytes: int
    free_bytes: int


class SambaStatusView(BaseModel):
    """What the server is doing right now."""

    is_active: bool
    sessions: list[SambaSessionView]
    disks: list[SambaDiskView]


class GiteaSettingsView(BaseModel):
    """The Gitea tab: configuration plus what the box actually has."""

    listen_port: int
    root_url: str
    is_registration_enabled: bool
    is_installed: bool
    is_active: bool
    version: str
    has_admin: bool
    admin_usernames: list[str] = Field(default_factory=list)


class GiteaConfigUpdate(BaseModel):
    """The Access group being saved."""

    listen_port: int
    root_url: str = ""
    is_registration_enabled: bool = False


class GiteaAdminCreate(BaseModel):
    """The first administrator, made from the panel because a Gitea with no
    accounts and registration off is a Gitea nobody can enter."""

    username: str = Field(min_length=1, max_length=39)
    password: str = Field(min_length=1, max_length=128)
    email: str = Field(min_length=3, max_length=254)


class GiteaPasswordUpdate(BaseModel):
    """A new password for an administrator — the recovery door, since a
    forgotten admin password cannot be fixed from inside Gitea."""

    password: str = Field(min_length=1, max_length=128)


class PodmanContainerView(BaseModel):
    """One declared container, as configured."""

    name: str
    image: str
    ports: list[str] = Field(default_factory=list)
    volumes: list[str] = Field(default_factory=list)
    environment: list[str] = Field(default_factory=list)
    command: str = ""
    is_autostart: bool = True


class PodmanContainerStateView(BaseModel):
    """One container as podman sees it right now, declared or not."""

    name: str
    image: str
    status: str
    is_running: bool
    is_declared: bool


class PodmanSettingsView(BaseModel):
    """The Containers tab: declarations beside what actually runs."""

    containers: list[PodmanContainerView]
    mirrors: list[str] = Field(default_factory=list)
    running: list[PodmanContainerStateView]
    is_installed: bool
    is_active: bool
    version: str


class PodmanContainerListUpdate(BaseModel):
    """The declared-containers group being saved."""

    containers: list[PodmanContainerView]


class PodmanMirrorListUpdate(BaseModel):
    """The registry-mirrors group being saved."""

    mirrors: list[str]


class PodmanTagListView(BaseModel):
    """Recent tags for one image, fetched from its registry best-effort."""

    tags: list[str] = Field(default_factory=list)


class NetbirdPeerView(BaseModel):
    """One other machine on the overlay, as this box sees it."""

    fqdn: str
    netbird_ip: str
    is_connected: bool
    connection_type: str
    latency_ms: int | None = None


class NetbirdView(BaseModel):
    """The NetBird tab: enrollment, the overlay, and the peers on it."""

    is_installed: bool
    is_active: bool
    version: str
    daemon_status: str
    is_enrolled: bool
    is_management_connected: bool
    management_url: str
    netbird_ip: str
    fqdn: str
    peers: list[NetbirdPeerView] = Field(default_factory=list)
    # The LAN networks this gateway serves, for the routes guidance: the
    # subnet route on the management plane should name exactly these.
    lan_subnets: list[str] = Field(default_factory=list)


class NetbirdJoinRequest(BaseModel):
    """A one-time enrollment; the key is used and never stored."""

    setup_key: str = Field(min_length=8, max_length=128)
    management_url: str = ""


# --- ZFS --------------------------------------------------------------------


class ZfsDiskView(BaseModel):
    """One physical disk, in a pool or waiting for one."""

    device: str
    by_id: str
    size_bytes: int
    model: str
    serial: str
    is_rotational: bool
    transport: str = ""
    wwn: str | None = None
    by_path: str | None = None
    fstype: str = ""
    pool: str | None = None
    is_available: bool = False
    smart_passed: bool | None = None
    temperature_c: int | None = None


class ZfsVdevMemberView(BaseModel):
    """One device inside a vdev."""

    name: str
    state: str
    read_errors: int = 0
    write_errors: int = 0
    checksum_errors: int = 0
    is_resilvering: bool = False


class ZfsVdevView(BaseModel):
    """One vdev of a pool."""

    name: str
    layout: str
    state: str
    members: list[ZfsVdevMemberView] = Field(default_factory=list)


class ZfsScanView(BaseModel):
    """What a pool's scrub or resilver is doing."""

    kind: str | None = None
    percent: float | None = None
    eta: str | None = None
    summary: str = ""


class ZfsDatasetView(BaseModel):
    """One filesystem dataset, with its achieved compression."""

    name: str
    used_bytes: int
    available_bytes: int
    mountpoint: str
    compression: str
    compressratio: float
    recordsize_bytes: int = 131072
    share: str | None = None


class ZfsPoolView(BaseModel):
    """One imported pool with its topology and datasets."""

    name: str
    state: str
    size_bytes: int
    allocated_bytes: int
    capacity_percent: int
    fragmentation_percent: int
    vdevs: list[ZfsVdevView] = Field(default_factory=list)
    scan: ZfsScanView = Field(default_factory=ZfsScanView)
    errors: str = ""
    datasets: list[ZfsDatasetView] = Field(default_factory=list)


class ZfsImportableView(BaseModel):
    """A pool found on attached disks, waiting to be imported."""

    name: str
    state: str


class ZfsSambaView(BaseModel):
    """What the share dialog needs to know about Samba."""

    is_ready: bool = False
    users: list[str] = Field(default_factory=list)


class ZfsView(BaseModel):
    """The ZFS page payload."""

    is_installed: bool
    pools: list[ZfsPoolView] = Field(default_factory=list)
    disks: list[ZfsDiskView] = Field(default_factory=list)
    importable: list[ZfsImportableView] = Field(default_factory=list)
    samba: ZfsSambaView = Field(default_factory=ZfsSambaView)


class ZfsPoolCreate(BaseModel):
    """A new pool: one vdev, defaults decided by the module."""

    name: str
    layout: str
    devices: list[str] = Field(min_length=1)
    is_forced: bool = False


class ZfsPoolExpand(BaseModel):
    """Another vdev for an existing pool; joining is permanent."""

    layout: str
    devices: list[str] = Field(min_length=1)
    is_forced: bool = False


class ZfsDiskActionRequest(BaseModel):
    """A member device to act on, as the topology names it."""

    device: str


class ZfsReplaceRequest(BaseModel):
    """Swap a member disk for a fresh one."""

    old_device: str
    new_device: str


class ZfsDatasetCreate(BaseModel):
    """A new dataset. Its tunables are fixed at creation, for its lifetime."""

    pool: str
    name: str
    compression: str
    recordsize: str = "128K"
    mountpoint: str | None = None


class ZfsDatasetRequest(BaseModel):
    """A dataset named in full."""

    dataset: str


class ZfsShareRequest(BaseModel):
    """Expose a dataset over Samba to the named users, or to everyone."""

    dataset: str
    # Empty means every configured user, current and future — the same
    # meaning the Samba module gives an empty valid_users.
    users: list[str] = Field(default_factory=list)

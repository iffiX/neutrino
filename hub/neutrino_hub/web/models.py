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
    # Carried on the frame rather than fetched separately: the status strip
    # shows both, and they are only true as of the moment the frame was taken.
    is_proxy_enabled: bool = True
    lan_device_count: int = 0
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


class KeyRename(BaseModel):
    """A new label for a stored key."""

    name: str


class AiProviderModelView(BaseModel):
    """One model alias a provider serves: real name in, served alias out."""

    name: str
    alias: str = ""


class AiProviderView(BaseModel):
    """One stored AI provider, without its key."""

    id: str
    name: str
    kind: str
    base_url: str = ""
    has_api_key: bool = False
    is_enabled: bool = True
    models: list[AiProviderModelView] = Field(default_factory=list)
    created_at: str = ""


class AiProviderListView(BaseModel):
    """The Credentials page's AI provider section."""

    providers: list[AiProviderView]


class AiProviderCreate(BaseModel):
    """A provider to store; the key travels one way."""

    name: str
    kind: str
    base_url: str = ""
    api_key: str = ""
    models: list[AiProviderModelView] = Field(default_factory=list)


class AiProviderUpdate(BaseModel):
    """Partial update to one provider; a blank key keeps the stored one."""

    name: str | None = None
    kind: str | None = None
    base_url: str | None = None
    api_key: str | None = None
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
    enabled_provider_count: int = 0


class CliproxyApiKeyCreate(BaseModel):
    """A client key to mint under a name."""

    name: str


class CliproxyApiSettingsUpdate(BaseModel):
    """The AI gateway's adjustable settings."""

    listen_port: int


class CliproxyApiApplyResult(BaseModel):
    """Outcome of rendering and restarting the AI gateway."""

    message: str


class DeviceSshConfig(BaseModel):
    """SSH credentials for one device.

    Key authentication references a stored key by ``key_id`` — the material
    lives in the key registry, not here. The password fields travel one way
    only: accepted on write, never sent back, with a ``has_`` flag standing in
    for the value.
    """

    host: str
    port: int = 22
    username: str
    auth: str = "key"
    key_id: str | None = None
    key_name: str | None = None
    password: str | None = None
    sudo_password: str | None = None
    has_sudo_password: bool = False


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


class DeviceClientInfoView(BaseModel):
    """Agent state and latest metrics for one device."""

    is_installed: bool = False
    # Whether the agent has checked in inside the heartbeat window. Not the
    # same question as `is_installed`, which records that an install was
    # asked for and is never cleared: a device whose agent is stopped, or
    # whose install failed, reads installed and answers nothing.
    is_online: bool = False
    version: str | None = None
    # True when the agent's version is not this hub's. The two ship together
    # and are only supported together, so the panel offers an upgrade rather
    # than trying to interoperate.
    is_version_mismatched: bool = False
    last_seen: str | None = None
    cpu_percent: float | None = None
    memory_percent: float | None = None
    disk_percent: float | None = None
    temperature_c: float | None = None
    uptime_s: int | None = None
    load_average: list[float] = Field(default_factory=list)
    cpu_core_percents: list[float] = Field(default_factory=list)
    gpus: list[DeviceGpuView] = Field(default_factory=list)
    processes: list[DeviceProcessView] = Field(default_factory=list)


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


class WolResult(BaseModel):
    """Outcome of sending a magic packet."""

    is_sent: bool
    message: str


class ServiceView(BaseModel):
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


class ServiceListView(BaseModel):
    """The Services tab payload."""

    services: list[ServiceView]


class ProvisionConsentView(BaseModel):
    """One thing installing would do that the person agrees to first.

    ``code`` says what kind of consequence it is and ``detail`` carries the
    values its sentence needs. The backend writes neither the sentence nor
    the title: wording belongs to the panel, which is what lets it be
    translated.
    """

    code: str
    detail: dict


class ServiceInstallPlanView(BaseModel):
    """What installing a module on this machine would actually do."""

    name: str
    is_consent_needed: bool
    consents: list[ProvisionConsentView]


class ServiceInstallRequest(BaseModel):
    """Whether the person has agreed to what the plan listed.

    False is the ordinary case: a module whose plan asks nothing installs on
    the press that started it.
    """

    is_consented: bool = False


class ServiceUninstallRequest(BaseModel):
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
    kernel: str
    uptime_s: int


class ClientHeartbeat(BaseModel):
    """A heartbeat posted by a neutrino_agent agent."""

    token: str
    hostname: str
    client_version: str
    metrics: dict = Field(default_factory=dict)
    # The agent's platform tuple, its held catalog hash, and what state each
    # feature it is reconciling is in. Absent from older agents, hence defaults.
    platform: dict = Field(default_factory=dict)
    catalog_hash: str = ""
    features: dict = Field(default_factory=dict)
    # Toggles made on the machine's own page, applied by the gateway and
    # reflected back in the reply so both sides agree within one beat.
    feature_requests: dict = Field(default_factory=dict)


class ClientCommand(BaseModel):
    """One queued command handed back to an agent."""

    id: str
    action: str
    args: dict = Field(default_factory=dict)


class ClientHeartbeatReply(BaseModel):
    """The gateway's answer to a heartbeat.

    ``catalog`` is sent only when the agent's ``catalog_hash`` is stale, so a
    converged fleet is not shipped it on every beat.
    """

    commands: list[ClientCommand] = Field(default_factory=list)
    desired_features: dict = Field(default_factory=dict)
    catalog: dict | None = None
    catalog_hash: str = ""


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
    platform: dict = Field(default_factory=dict)


class ClientEnrollReply(BaseModel):
    """What the gateway hands back once a machine has joined."""

    token: str
    mac_address: str


class DeviceFeatureView(BaseModel):
    """One managed feature, as the panel shows it for a device."""

    name: str
    title: str
    description: str = ""
    is_supported: bool = True
    is_enabled: bool = False
    # False for things that must not be taken off a managed machine, chiefly
    # the SSH server the hub reaches it through.
    is_removable: bool = True
    # Whether installing and pointing at the hub are separate steps, as they
    # are for cc-switch, which can be installed and aimed elsewhere.
    has_activation: bool = False
    is_activated: bool = False
    is_active: bool = False
    state: str = "unknown"
    message: str = ""


class DeviceFeatureListView(BaseModel):
    """Every feature a device could run, with its state.

    ``is_agent_online`` is what makes the list readable: every feature's state
    comes from the agent, so with no agent answering they are all unknown, and
    a page that cannot say why draws them as "not installed" beside a remote
    desktop it can see running.
    """

    features: list[DeviceFeatureView] = Field(default_factory=list)
    is_agent_installed: bool = False
    is_agent_online: bool = False


class DeviceFeatureUpdate(BaseModel):
    """Change what is wanted of one feature; absent fields are left alone."""

    is_enabled: bool | None = None
    is_activated: bool | None = None


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

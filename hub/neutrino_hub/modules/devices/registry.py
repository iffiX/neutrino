"""The LAN device list the panel shows.

Two sources are merged by MAC address: what a scan finds right now, and what the
user has annotated in ``config/devices/devices.json``. A scanned device the user
has never touched is shown but not stored; the moment it gets a name or SSH
credentials it becomes a stored device and survives reboots.
"""

import secrets
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

from neutrino_hub.utils.json_file import read_config, write_config

from neutrino_hub.modules.devices.constants import DEVICE_AGENT_ONLINE_WINDOW_S
from neutrino_hub.modules.devices.host_keys import DeviceHostKeyStore
from neutrino_hub.modules.devices.lan_scan import DiscoveredDevice

DEVICES_CONFIG_PATH = "devices/devices.json"
AGENT_TOKEN_BYTES = 24


def feature_wish(stored) -> dict:
    """Normalise what is stored for one feature into the two wishes.

    Args:
        stored: What ``devices.json`` holds — a bare bool from before
            activation existed, the pair, or nothing.

    Returns:
        ``{"is_enabled", "is_activated"}``.
    """
    if isinstance(stored, dict):
        return {
            "is_enabled": bool(stored.get("is_enabled")),
            "is_activated": bool(stored.get("is_activated")),
        }
    return {"is_enabled": bool(stored), "is_activated": False}


@dataclass
class DeviceClientInfo:
    """State reported by the neutrino_agent agent on a device.

    Attributes:
        token: Shared secret the agent authenticates its heartbeats with; a
            token nobody has used yet is an offer, not management.
        version: Agent version from the last heartbeat.
        last_seen: ISO timestamp of the last heartbeat.
        cpu_percent: Latest processor load, when reported.
        memory_percent: Latest memory use, when reported.
        disk_percent: Latest root filesystem use, when reported.
        temperature_c: Latest temperature, when the device exposes one.
        features: What the user asked of each managed feature, by name:
            ``{"is_enabled", "is_activated"}``. Installing and activating are
            separate wishes — cc-switch can be on a machine without pointing
            at this hub.
        ai_key_id: The cliproxyapi client key minted for this device's AI tools.
        target_user: The account whose home the agent writes tool configs into.
    """

    token: str | None = None
    version: str | None = None
    last_seen: str | None = None
    cpu_percent: float | None = None
    memory_percent: float | None = None
    disk_percent: float | None = None
    temperature_c: float | None = None
    features: dict = field(default_factory=dict)
    ai_key_id: str | None = None
    target_user: str | None = None

    @classmethod
    def from_dict(cls, data: dict) -> "DeviceClientInfo":
        """Build from the stored ``client`` block.

        Args:
            data: The stored block.

        Returns:
            The parsed info.
        """
        return cls(
            token=data.get("token"),
            version=data.get("version"),
            last_seen=data.get("last_seen"),
            features=data.get("features", {}),
            ai_key_id=data.get("ai_key_id"),
            target_user=data.get("target_user"),
        )

    def to_dict(self) -> dict:
        """Serialize the persistent fields.

        Live metrics are deliberately not stored: they are runtime state that
        would be stale the moment the panel restarts.

        Returns:
            A JSON-ready object.
        """
        return {
            "token": self.token,
            "version": self.version,
            "last_seen": self.last_seen,
            "features": self.features,
            "ai_key_id": self.ai_key_id,
            "target_user": self.target_user,
        }


@dataclass
class ManagedDevice:
    """One device, as stored plus whatever the latest scan learned.

    Attributes:
        mac_address: Lower-case MAC, the identity.
        ipv4_address: Address from the latest scan or the stored SSH host.
        name: User-chosen label.
        icon: User-chosen icon key.
        vendor: OUI vendor string from the scan.
        is_online: Whether the latest scan saw it.
        is_wol_enabled: Whether the user marked it wakeable.
        ssh: Stored SSH settings, when configured.
        client: Agent state.
    """

    mac_address: str
    ipv4_address: str = ""
    name: str | None = None
    icon: str | None = None
    vendor: str = ""
    is_online: bool = False
    is_wol_enabled: bool = False
    ssh: dict | None = None
    client: DeviceClientInfo = field(default_factory=DeviceClientInfo)

    @property
    def has_ssh(self) -> bool:
        """Whether SSH credentials are stored for this device."""
        return bool(self.ssh and self.ssh.get("host") and self.ssh.get("username"))

    @property
    def is_managed(self) -> bool:
        """Whether an agent completed its handshake and still holds a token.

        A token alone is an offer — an install that failed after minting
        leaves one dangling, invisibly — and the first authenticated
        heartbeat is what turns the offer into management. The hub lets go
        by deleting the token; the device lets go by leaving.
        """
        return bool(self.client.token and self.client.last_seen)

    @property
    def is_agent_online(self) -> bool:
        """Whether this device's agent has beaten inside the window.

        On the device rather than in the panel, because two callers ask it:
        the page that draws one device, and the strip that counts them.

        Returns:
            False when there is no agent, no heartbeat yet, or the last one is
            older than :data:`DEVICE_AGENT_ONLINE_WINDOW_S`. An SSH login is
            not an agent and never counts here.
        """
        if not self.is_managed:
            return False
        try:
            seen = datetime.fromisoformat(self.client.last_seen)
        except ValueError:
            return False
        if seen.tzinfo is None:
            seen = seen.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - seen).total_seconds()
        return age <= DEVICE_AGENT_ONLINE_WINDOW_S

    @property
    def is_stored(self) -> bool:
        """Whether this device has anything worth persisting."""
        return bool(self.name or self.ssh or self.is_wol_enabled or self.client.token)

    def to_dict(self) -> dict:
        """Serialize to the ``devices.json`` shape.

        Returns:
            A JSON-ready object.
        """
        return {
            "name": self.name,
            "icon": self.icon,
            "is_wol_enabled": self.is_wol_enabled,
            "ssh": self.ssh,
            "client": self.client.to_dict(),
        }


# Held across every read-modify-write of the device file. The panel is one
# process with many threads — a heartbeat, a page load and a save all land at
# once — and the file is written whole.
_WRITE_LOCK = threading.RLock()


class DeviceRegistry:
    """Reads, merges, and writes the device list.

    Every write re-reads the file first. An agent beats every five seconds and
    each beat rewrites the whole list, so a panel action that took its own
    snapshot a moment earlier would put every other device back as it was —
    including one somebody has just forgotten, credentials and all.
    """

    def __init__(self):
        self._stored = self._read_stored()

    def merged(self, discovered: list[DiscoveredDevice]) -> list[ManagedDevice]:
        """Combine stored annotations with a scan result.

        Args:
            discovered: What the latest scan found; may be empty, in which case
                only stored devices are returned and all are marked offline.

        Returns:
            Every known device, stored ones first, then scan-only ones.
        """
        by_mac: dict[str, ManagedDevice] = {}
        for mac_address, entry in self._stored.items():
            by_mac[mac_address] = self._from_stored(mac_address, entry)
        for device in discovered:
            existing = by_mac.get(device.mac_address)
            if existing is None:
                by_mac[device.mac_address] = ManagedDevice(
                    mac_address=device.mac_address,
                    ipv4_address=device.ipv4_address,
                    vendor=device.vendor,
                    is_online=device.is_online,
                )
                continue
            existing.ipv4_address = device.ipv4_address or existing.ipv4_address
            existing.vendor = device.vendor or existing.vendor
            existing.is_online = device.is_online
        return sorted(
            by_mac.values(),
            key=lambda item: (not item.is_stored, not item.is_online, item.mac_address),
        )

    def get(self, mac_address: str) -> ManagedDevice:
        """Read one stored device.

        Args:
            mac_address: The device's MAC.

        Returns:
            The stored device, or a blank one when nothing is stored yet.
        """
        mac_address = mac_address.lower()
        entry = self._stored.get(mac_address)
        if entry is None:
            return ManagedDevice(mac_address=mac_address)
        return self._from_stored(mac_address, entry)

    def all_stored(self) -> list[ManagedDevice]:
        """Read every annotated device, without scanning.

        Returns:
            One device per stored entry. Used to count which devices reference
            a given SSH key.
        """
        return [
            self._from_stored(mac_address, entry)
            for mac_address, entry in self._stored.items()
        ]

    def annotate(self, mac_address: str, annotation: dict) -> ManagedDevice:
        """Apply a partial update to one device and persist it.

        Args:
            mac_address: The device's MAC.
            annotation: Any of ``name``, ``icon``, ``is_wol_enabled``, ``ssh``.

        Returns:
            The stored device after the update.
        """
        with _WRITE_LOCK:
            device = self._fresh(mac_address)
            if "name" in annotation:
                device.name = annotation["name"]
            if "icon" in annotation:
                device.icon = annotation["icon"]
            if "is_wol_enabled" in annotation:
                device.is_wol_enabled = bool(annotation["is_wol_enabled"])
            if "ssh" in annotation:
                device.ssh = annotation["ssh"]
            self._store(device)
            return device

    def forget(self, mac_address: str) -> None:
        """Drop a device's stored annotations, and the host key pinned to it.

        Dropping the key matters: adding a device again is the way somebody
        says a rebuilt machine's new key is legitimate, and it would not work
        if the old key outlived the record.

        Args:
            mac_address: The device's MAC. Unknown addresses are ignored.
        """
        with _WRITE_LOCK:
            self._stored = self._read_stored()
            entry = self._stored.get(mac_address.lower(), {})
            ssh = entry.get("ssh") or {}
            # Only where no other record still points at that address: the
            # store is keyed by host and port, and a machine whose MAC changed
            # is two records on one host. Forgetting the stale one would
            # unpin the live one.
            if ssh.get("host") and not self._others_on(mac_address, ssh):
                DeviceHostKeyStore().forget(ssh["host"], ssh.get("port", 22))
            self._stored.pop(mac_address.lower(), None)
            self._write_stored()

    def _others_on(self, mac_address: str, ssh: dict) -> bool:
        """Whether another stored device is reached at this host and port.

        Args:
            mac_address: The device being forgotten.
            ssh: Its SSH settings.

        Returns:
            True when some other record names the same address.
        """
        for other_mac, entry in self._stored.items():
            if other_mac == mac_address.lower():
                continue
            other = entry.get("ssh") or {}
            if other.get("host") == ssh.get("host") and other.get(
                "port", 22
            ) == ssh.get("port", 22):
                return True
        return False

    def issue_client_token(self, mac_address: str) -> str:
        """Create and store a heartbeat token for a device.

        A fresh token is generated every time the agent is installed, so
        reinstalling invalidates the old one. The device does not become
        managed here: an install can still fail after the token exists, and
        it is the first heartbeat that proves an agent is really there.

        Args:
            mac_address: The device's MAC.

        Returns:
            The new token.
        """
        with _WRITE_LOCK:
            device = self._fresh(mac_address)
            device.client.token = secrets.token_urlsafe(AGENT_TOKEN_BYTES)
            self._store(device)
            return device.client.token

    def find_by_client_token(self, token: str) -> ManagedDevice | None:
        """Look up the device a heartbeat token belongs to.

        Args:
            token: The token presented by an agent.

        Returns:
            The matching device, or None when the token is unknown.
        """
        for mac_address, entry in self._stored.items():
            stored_token = entry.get("client", {}).get("token")
            if stored_token and secrets.compare_digest(stored_token, token):
                return self._from_stored(mac_address, entry)
        return None

    def record_heartbeat(self, mac_address: str, *, version: str, seen_at: str) -> None:
        """Persist the agent version and last-seen time from a heartbeat.

        Args:
            mac_address: The device's MAC.
            version: Agent version it reported.
            seen_at: ISO timestamp of the heartbeat.
        """
        with _WRITE_LOCK:
            device = self._fresh(mac_address)
            device.client.version = version
            device.client.last_seen = seen_at
            self._store(device)

    def forget_client(self, mac_address: str) -> None:
        """Record that a device's agent has left.

        The token is dropped so the old one cannot beat again, and the agent
        state goes with it. Everything the user typed — the name, the icon,
        the SSH credentials — survives: the machine is still theirs, it is
        only no longer running an agent.

        Args:
            mac_address: The device's MAC.
        """
        with _WRITE_LOCK:
            device = self._fresh(mac_address)
            device.client.token = None
            device.client.version = None
            device.client.last_seen = None
            device.client.features = {}
            self._store(device)

    def set_feature(
        self,
        mac_address: str,
        feature: str,
        *,
        is_enabled: bool | None = None,
        is_activated: bool | None = None,
    ) -> ManagedDevice:
        """Change what is wanted of one managed feature.

        The two wishes are independent and either can be left alone: a device
        can have cc-switch installed without it pointing at this hub.
        Uninstalling implies deactivating, since there is nothing left to
        point.

        Args:
            mac_address: The device's MAC.
            feature: The feature name.
            is_enabled: Whether the agent should keep it installed.
            is_activated: Whether it should point at this hub.

        Returns:
            The device after the change.
        """
        with _WRITE_LOCK:
            device = self._fresh(mac_address)
            wanted = feature_wish(device.client.features.get(feature))
            if is_enabled is not None:
                wanted["is_enabled"] = is_enabled
                if not is_enabled:
                    wanted["is_activated"] = False
            if is_activated is not None:
                wanted["is_activated"] = is_activated
                if is_activated:
                    wanted["is_enabled"] = True
            device.client.features[feature] = wanted
            self._store(device)
            return device

    def set_ai_key_id(self, mac_address: str, key_id: str | None) -> None:
        """Remember which cliproxyapi client key belongs to a device.

        Args:
            mac_address: The device's MAC.
            key_id: The key's id, or None to forget it.
        """
        with _WRITE_LOCK:
            device = self._fresh(mac_address)
            device.client.ai_key_id = key_id
            self._store(device)

    def set_target_user(self, mac_address: str, username: str) -> ManagedDevice:
        """Set the account the agent writes AI tool configs into.

        Args:
            mac_address: The device's MAC.
            username: The login account on the device.

        Returns:
            The device after the change.
        """
        with _WRITE_LOCK:
            device = self._fresh(mac_address)
            device.client.target_user = username
            self._store(device)
            return device

    def _from_stored(self, mac_address: str, entry: dict) -> ManagedDevice:
        ssh = entry.get("ssh")
        return ManagedDevice(
            mac_address=mac_address,
            ipv4_address=(ssh or {}).get("host", ""),
            name=entry.get("name"),
            icon=entry.get("icon"),
            is_wol_enabled=entry.get("is_wol_enabled", False),
            ssh=ssh,
            client=DeviceClientInfo.from_dict(entry.get("client", {})),
        )

    def _fresh(self, mac_address: str) -> ManagedDevice:
        """One device read again under the write lock, so a mutation starts
        from what is on disk and not from this instance's snapshot."""
        self._stored = self._read_stored()
        return self.get(mac_address)

    def _store(self, device: ManagedDevice) -> None:
        with _WRITE_LOCK:
            # Re-read inside the lock: what this holds is one device, and
            # writing a snapshot taken before somebody else's change would
            # undo theirs.
            self._stored = self._read_stored()
            self._stored[device.mac_address] = device.to_dict()
            self._write_stored()

    def _read_stored(self) -> dict:
        try:
            data = read_config(DEVICES_CONFIG_PATH)
        except FileNotFoundError:
            return {}
        return {
            mac_address.lower(): entry
            for mac_address, entry in data.get("devices", {}).items()
        }

    def _write_stored(self) -> None:
        write_config(DEVICES_CONFIG_PATH, {"devices": self._stored})

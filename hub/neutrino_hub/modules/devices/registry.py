"""The LAN device list the panel shows.

Two sources are merged by MAC address: what a scan finds right now, and what the
user has annotated in ``config/devices/devices.json``. A scanned device the user
has never touched is shown but not stored; the moment it gets a name or SSH
credentials it becomes a stored device and survives reboots.
"""

import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone

from neutrino_hub.utils.json_file import (
    CONFIG_WRITE_LOCK,
    read_config,
    write_config,
)

from neutrino_hub.modules.devices.host_keys import DeviceHostKeyStore
from neutrino_hub.modules.devices.lan_scan import DiscoveredDevice

DEVICES_CONFIG_PATH = "devices/devices.json"
AGENT_TOKEN_BYTES = 24


def _token_digest(token: str) -> str:
    """The stored form of a heartbeat token.

    Args:
        token: The raw token an agent holds.

    Returns:
        Its SHA-256 hex.
    """
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class DeviceClientInfo:
    """State reported by the neutrino_agent agent on a device.

    Attributes:
        token_sha256: SHA-256 hex of the shared secret the agent
            authenticates its heartbeats with; the raw token exists only in
            the enroll reply and on the device. A token nobody has used yet
            is an offer, not management.
        version: Agent version from the last heartbeat.
        last_seen: ISO timestamp of the last heartbeat.
        ai_key_ids: The cliproxyapi client key generated for each of this
            device's activated accounts, by account name.
    """

    token_sha256: str | None = None
    version: str | None = None
    last_seen: str | None = None
    ai_key_ids: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "DeviceClientInfo":
        """Build from the stored ``client`` block.

        Args:
            data: The stored block.

        Returns:
            The parsed info.
        """
        return cls(
            token_sha256=data.get("token_sha256"),
            version=data.get("version"),
            last_seen=data.get("last_seen"),
            ai_key_ids=data.get("ai_key_ids", {}),
        )

    def to_dict(self) -> dict:
        """Serialize the persistent fields.

        Live metrics are deliberately not stored: they are runtime state that
        would be stale the moment the panel restarts. What each module is
        stands in the agent's own reports; the hub keeps no record of what a
        machine should have.

        Returns:
            A JSON-ready object.
        """
        return {
            "token_sha256": self.token_sha256,
            "version": self.version,
            "last_seen": self.last_seen,
            "ai_key_ids": self.ai_key_ids,
        }


@dataclass
class ManagedDevice:
    """One device, as stored plus whatever the latest scan learned.

    Attributes:
        mac_address: Lower-case MAC, the identity.
        ipv4_address: Address from the latest scan. Where a machine is
            reached from is the agent channel's business, not SSH's: an
            agent joined by a link has no SSH host and is no less located.
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

        A token alone is an offer — an install that failed after generating
        leaves one dangling, invisibly — and the first authenticated
        heartbeat is what turns the offer into management. The hub lets go
        by deleting the token; the device lets go by leaving.
        """
        return bool(self.client.token_sha256 and self.client.last_seen)

    @property
    def is_stored(self) -> bool:
        """Whether this device has anything worth persisting."""
        return bool(
            self.name or self.ssh or self.is_wol_enabled or self.client.token_sha256
        )

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


# The config-wide lock, held across every read-modify-write of the device
# file. The panel is one process with many threads — a heartbeat, a page load
# and a save all land at once — and the file is written whole.
_WRITE_LOCK = CONFIG_WRITE_LOCK


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
        """Create a heartbeat token for a device, storing only its hash.

        A fresh token is generated every time the agent is installed, so
        reinstalling invalidates the old one. The raw token goes to the
        device and nowhere else; ``devices.json`` holds its SHA-256, so the
        file authenticates heartbeats without carrying what an agent
        presents. The device does not become managed here: an install can
        still fail after the token exists, and it is the first heartbeat
        that proves an agent is really there.

        Args:
            mac_address: The device's MAC.

        Returns:
            The new raw token, for the enroll reply alone.
        """
        with _WRITE_LOCK:
            device = self._fresh(mac_address)
            token = secrets.token_urlsafe(AGENT_TOKEN_BYTES)
            device.client.token_sha256 = _token_digest(token)
            self._store(device)
            return token

    def find_by_client_token(self, token: str) -> ManagedDevice | None:
        """Look up the device a heartbeat token belongs to.

        Args:
            token: The token presented by an agent.

        Returns:
            The matching device, or None when the token is unknown.
        """
        presented = _token_digest(token)
        for mac_address, entry in self._stored.items():
            stored = entry.get("client", {}).get("token_sha256")
            if stored and secrets.compare_digest(stored, presented):
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
            device.client.token_sha256 = None
            device.client.version = None
            device.client.last_seen = None
            self._store(device)

    def set_ai_key_id(self, mac_address: str, account: str, key_id: str | None) -> None:
        """Remember which cliproxyapi client key one account on a device holds.

        Args:
            mac_address: The device's MAC.
            account: The human account on the device.
            key_id: The key's id, or None to forget the pair.
        """
        with _WRITE_LOCK:
            device = self._fresh(mac_address)
            if key_id is None:
                device.client.ai_key_ids.pop(account, None)
            else:
                device.client.ai_key_ids[account] = key_id
            self._store(device)

    def _from_stored(self, mac_address: str, entry: dict) -> ManagedDevice:
        ssh = entry.get("ssh")
        return ManagedDevice(
            mac_address=mac_address,
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

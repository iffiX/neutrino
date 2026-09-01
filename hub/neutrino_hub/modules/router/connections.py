"""The wireless networks this box knows how to join.

One entry per network, holding what `wpa_supplicant` needs to associate with
it and nothing else. This is a decision rather than state: somebody typed the
passphrase, or somebody typed it into another manager on this machine once and
it was read from there, and backing up `/etc/neutrino/` has to bring a box back
able to reach the network it lives on.

The file is a secret. It is `.gitignore`d, written 0600, and never comes back
out through the API — a listing says a network is known, never what its key is.

Pure: this module parses and shapes configuration. Rendering it for
`wpa_supplicant` is :mod:`neutrino_hub.modules.router.supplicant_renderer`,
and reading somebody else's store into it is
:mod:`neutrino_hub.modules.router.credentials`.
"""

from dataclasses import dataclass, field

from neutrino_hub.modules.router.constants import (
    ROUTER_KEY_MGMT_NONE,
    ROUTER_KEY_MGMT_PSK,
    ROUTER_KEY_MGMT_SAE,
    ROUTER_KEY_MGMTS,
    ROUTER_SOURCE_PANEL,
)

# Where a profile sits when nobody has ranked it. wpa_supplicant prefers the
# highest, and every network somebody adds by hand lands here — the order they
# were added in is not a preference anybody expressed.
CONNECTION_DEFAULT_PRIORITY = 0


@dataclass
class RouterConnection:
    """One wireless network and how to authenticate to it.

    Attributes:
        ssid: The network name, as it is broadcast.
        key_mgmt: ``WPA-PSK``, ``SAE`` for WPA3, or ``NONE`` for an open
            network. Nothing else is stored: an enterprise network needs a
            certificate and an identity, which is not something this asks for
            and not something it should half-hold.
        psk: The secret, in the one of two forms `wpa_supplicant` accepts —
            64 hexadecimal characters for a derived key, or the passphrase
            itself. Empty for an open network, and empty for a network whose
            passphrase was held somewhere this could not read, which is a
            network the panel asks about once.
        priority: Which network to prefer where two are in range. Higher wins.
        is_hidden: Whether the network has to be probed for by name because it
            does not broadcast one.
        source: Where the entry came from — ``panel`` for one somebody typed,
            or ``inherited:<manager>`` for one read out of what this machine
            already held.
    """

    ssid: str
    key_mgmt: str = ROUTER_KEY_MGMT_PSK
    psk: str = ""
    priority: int = CONNECTION_DEFAULT_PRIORITY
    is_hidden: bool = False
    source: str = ROUTER_SOURCE_PANEL

    @property
    def is_open(self) -> bool:
        """Whether the network takes no key at all."""
        return self.key_mgmt == ROUTER_KEY_MGMT_NONE

    @property
    def has_secret(self) -> bool:
        """Whether this entry can actually associate.

        An open network needs no secret; anything else with an empty one was
        read from a store that kept its key somewhere else, and is a network
        the panel has to ask about before the radio can join it.
        """
        return self.is_open or bool(self.psk)

    @classmethod
    def from_dict(cls, data: dict) -> "RouterConnection":
        """Parse one entry.

        Args:
            data: An entry of the ``connections`` list.

        Returns:
            The parsed network. An unrecognised key management reads as
            ``WPA-PSK``, which is what all but a handful of networks are.
        """
        key_mgmt = str(data.get("key_mgmt", ROUTER_KEY_MGMT_PSK)).upper()
        return cls(
            ssid=str(data["ssid"]),
            key_mgmt=key_mgmt if key_mgmt in ROUTER_KEY_MGMTS else ROUTER_KEY_MGMT_PSK,
            psk=str(data.get("psk", "")),
            priority=int(data.get("priority", CONNECTION_DEFAULT_PRIORITY)),
            is_hidden=bool(data.get("is_hidden", False)),
            source=str(data.get("source", ROUTER_SOURCE_PANEL)),
        )

    def to_dict(self) -> dict:
        """Serialize back to the config shape.

        Returns:
            A plain object ready for ``config/router/connections.json``.
        """
        return {
            "ssid": self.ssid,
            "key_mgmt": self.key_mgmt,
            "psk": self.psk,
            "priority": self.priority,
            "is_hidden": self.is_hidden,
            "source": self.source,
        }


@dataclass
class RouterConnectionSet:
    """The whole of ``config/router/connections.json``.

    Attributes:
        connections: Every network the box knows, in no particular order —
            what to prefer is ``priority``, not position.
    """

    connections: list[RouterConnection] = field(default_factory=list)

    @property
    def ssids(self) -> set[str]:
        """Every network name held, for asking whether one is already known."""
        return {connection.ssid for connection in self.connections}

    def find(self, ssid: str) -> RouterConnection | None:
        """One network by name.

        Args:
            ssid: The network name.

        Returns:
            The entry, or None when the box does not know it.
        """
        for connection in self.connections:
            if connection.ssid == ssid:
                return connection
        return None

    def replace(self, connection: RouterConnection) -> None:
        """Add a network, or update the one already held under its name.

        An SSID is the identity: joining a network somebody has joined before
        is the same network with a new key, not a second entry that would give
        the supplicant two answers for one question.

        Args:
            connection: The network to store.
        """
        for index, existing in enumerate(self.connections):
            if existing.ssid == connection.ssid:
                self.connections[index] = connection
                return
        self.connections.append(connection)

    def remove(self, ssid: str) -> bool:
        """Forget a network.

        Args:
            ssid: The network name.

        Returns:
            True when one was removed.
        """
        for index, existing in enumerate(self.connections):
            if existing.ssid == ssid:
                del self.connections[index]
                return True
        return False

    def joinable(self) -> list["RouterConnection"]:
        """The networks that can actually be associated with, best first.

        An entry whose key could not be read is left out rather than rendered:
        `wpa_supplicant` would take it, try it, and fail every time the network
        came into range, which reads as a radio that cannot connect rather than
        as a passphrase nobody has typed yet.

        Returns:
            Entries with a secret, highest priority first and by name within
            a priority so the rendered file does not reshuffle between runs.
        """
        return sorted(
            (item for item in self.connections if item.has_secret),
            key=lambda item: (-item.priority, item.ssid),
        )

    @classmethod
    def from_dict(cls, data: dict) -> "RouterConnectionSet":
        """Parse the whole file.

        Args:
            data: The parsed JSON object.

        Returns:
            The set, with entries carrying no SSID dropped — an entry nothing
            can be looked up by is not a network.
        """
        connections = []
        for entry in data.get("connections", []):
            if isinstance(entry, dict) and entry.get("ssid"):
                connections.append(RouterConnection.from_dict(entry))
        return cls(connections=connections)

    def to_dict(self) -> dict:
        """Serialize back to the config shape.

        Returns:
            A plain object ready for ``config/router/connections.json``.
        """
        return {"connections": [item.to_dict() for item in self.connections]}

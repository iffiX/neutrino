"""Composing the catalog a heartbeat answers with, behind a cache.

The catalog has two halves under one hash: the function manifests, and the
service offers rendered from the hub's own state. Composing it reads half a
dozen files and the container cache, and an agent beats every few seconds,
so the composition is keyed on cheap stamps — file mtimes, binary presence,
the container cache's generation — and rebuilt only when one moves.
"""

import hashlib
import json

from neutrino_hub.modules.ai.constants import AI_PROVIDERS_PATH
from neutrino_hub.modules.ai.registry import AiProviderRegistry
from neutrino_hub.modules.cliproxyapi.constants import (
    CLIPROXYAPI_AUTH_RELATIVE,
    CLIPROXYAPI_BINARY_PATH,
)
from neutrino_hub.modules.functions.manifests import (
    load_function_manifests,
    manifests_stamp,
)
from neutrino_hub.modules.gitea.config import GiteaConfig
from neutrino_hub.modules.gitea.constants import GITEA_BINARY_PATH
from neutrino_hub.modules.router.interfaces import RouterNetworkConfig
from neutrino_hub.modules.services.config import DeclaredServiceRegistry
from neutrino_hub.modules.services.docker import DockerContainerCache
from neutrino_hub.modules.services.offers import ServiceOfferRenderer
from neutrino_hub.utils import constants as utils_constants
from neutrino_hub.utils import json_file

# The config files whose content shapes the catalog; a change to any of them
# is what invalidates the composed copy.
CATALOG_CONFIG_STAMPS = (
    "services/declared.json",
    "samba/samba.json",
    "router/network.json",
    "gitea/gitea.json",
    AI_PROVIDERS_PATH,
)


class DeviceCatalogCache:
    """Composes and hashes the catalog, rebuilding only on a moved stamp."""

    def __init__(self, *, docker_cache: DockerContainerCache):
        """
        Args:
            docker_cache: The shared container cache; its generation is part
                of the stamp, so a changed container list recomposes.
        """
        self._docker_cache = docker_cache
        self._stamp: tuple | None = None
        self._catalog: dict = {}
        self._hash = ""

    def catalog(self) -> tuple[dict, str]:
        """The catalog and its hash, recomposed only when a stamp moved.

        Returns:
            ``({"functions", "services"}, hash)``.
        """
        declared = DeclaredServiceRegistry().list_records()
        self._docker_cache.results(declared)
        stamp = self._current_stamp()
        if stamp != self._stamp:
            self._compose(declared)
            self._stamp = stamp
        return self._catalog, self._hash

    def _compose(self, declared) -> None:
        hub_address = self._hub_address()
        offers = ServiceOfferRenderer(
            hub_address=hub_address,
            hub_share_names=self._hub_share_names(),
            declared_services=declared,
            is_gitea_installed=GITEA_BINARY_PATH.is_file(),
            gitea_url=self._gitea_url(hub_address),
            docker_containers=self._docker_cache.results(declared),
            is_ai_served=self._is_ai_served(),
        ).render()
        self._catalog = {
            "functions": load_function_manifests(),
            "services": offers,
        }
        serialized = json.dumps(self._catalog, sort_keys=True).encode("utf-8")
        self._hash = hashlib.sha256(serialized).hexdigest()[:16]

    def _current_stamp(self) -> tuple:
        entries = [manifests_stamp(), self._docker_cache.generation]
        for relative in CATALOG_CONFIG_STAMPS:
            path = json_file.UTILS_CONFIG_DIR / relative
            try:
                entries.append(path.stat().st_mtime_ns)
            except OSError:
                entries.append(None)
        auth_dir = utils_constants.UTILS_STATE_ROOT / CLIPROXYAPI_AUTH_RELATIVE
        try:
            entries.append(auth_dir.stat().st_mtime_ns)
        except OSError:
            entries.append(None)
        entries.append(GITEA_BINARY_PATH.is_file())
        entries.append(CLIPROXYAPI_BINARY_PATH.is_file())
        return tuple(entries)

    def _hub_address(self) -> str:
        try:
            network = RouterNetworkConfig.from_dict(
                json_file.read_config("router/network.json")
            )
        except (FileNotFoundError, ValueError):
            return ""
        return network.primary_lan_address or ""

    def _hub_share_names(self) -> list[str]:
        try:
            data = json_file.read_config("samba/samba.json")
        except (FileNotFoundError, ValueError):
            return []
        return [
            str(share.get("name", ""))
            for share in data.get("shares", [])
            if share.get("name")
        ]

    def _gitea_url(self, hub_address: str) -> str:
        try:
            config = GiteaConfig.from_dict(json_file.read_config("gitea/gitea.json"))
        except (FileNotFoundError, ValueError):
            config = GiteaConfig()
        if config.root_url:
            return config.root_url
        if not hub_address:
            return ""
        return f"http://{hub_address}:{config.listen_port}/"

    def _is_ai_served(self) -> bool:
        """Whether the gateway has anything to serve a device with.

        Returns:
            True when the binary is on the box and at least one enabled
            keyed provider or one signed-in account feeds it.
        """
        if not CLIPROXYAPI_BINARY_PATH.is_file():
            return False
        for provider in AiProviderRegistry().list_records():
            if provider.is_enabled and provider.secret_id:
                return True
        auth_dir = utils_constants.UTILS_STATE_ROOT / CLIPROXYAPI_AUTH_RELATIVE
        if not auth_dir.is_dir():
            return False
        return any(path.suffix == ".json" for path in auth_dir.iterdir())

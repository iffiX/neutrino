"""Making the AI gateway's configuration true on the box.

Not pure: writes the generated file, restarts the unit, and probes the
running service.
"""

import httpx

from neutrino_hub.system.constants import SYSTEM_SYSTEMD_DIR
from neutrino_hub.utils.constants import UTILS_GENERATED_DIR
from neutrino_hub.utils.json_file import read_config, write_config, write_generated
from neutrino_hub.utils.subprocess_run import run

from neutrino_hub.modules.cliproxy.config import CliproxyConfig
from neutrino_hub.modules.cliproxy.constants import (
    CLIPROXY_BINARY_PATH,
    CLIPROXY_GENERATED_NAME,
    CLIPROXY_UNIT,
)
from neutrino_hub.modules.cliproxy.renderer import CliproxyConfigRenderer
from neutrino_hub.modules.credentials.registry import AiProviderRegistry

CLIPROXY_CONFIG_PATH = "cliproxy/cliproxy.json"
PROBE_TIMEOUT_S = 5


def load_config() -> CliproxyConfig:
    """Read the stored settings, empty defaults when the file is missing.

    Returns:
        The parsed configuration.
    """
    try:
        return CliproxyConfig.from_dict(read_config(CLIPROXY_CONFIG_PATH))
    except FileNotFoundError:
        return CliproxyConfig()


def save_config(config: CliproxyConfig) -> None:
    """Write the settings back.

    Args:
        config: The configuration to store.
    """
    write_config(CLIPROXY_CONFIG_PATH, config.to_dict())


class CliproxyConfigApplier:
    """Renders the YAML and restarts the service to pick it up."""

    def apply(self) -> str:
        """Render from the stored state and restart the gateway.

        Returns:
            A one-line summary of what happened.

        Raises:
            ValueError: If the stored settings do not validate.
        """
        config = load_config()
        config.validate()
        providers = AiProviderRegistry().list_records()
        rendered = CliproxyConfigRenderer(config=config, providers=providers).render()
        write_generated(
            UTILS_GENERATED_DIR / CLIPROXY_GENERATED_NAME, rendered, mode=0o600
        )
        if not self.is_installed:
            return "rendered; the service is not installed yet"
        run(["systemctl", "restart", CLIPROXY_UNIT])
        enabled = sum(1 for p in providers if p.is_enabled and p.api_key)
        return f"applied with {enabled} provider(s) and restarted"

    def refresh_unit(self, unit_text: str) -> bool:
        """Install or update the systemd unit, telling whether it changed.

        Args:
            unit_text: The packaged unit's content.

        Returns:
            Whether anything was written.
        """
        unit_path = SYSTEM_SYSTEMD_DIR / CLIPROXY_UNIT
        if unit_path.is_file() and unit_path.read_text(encoding="utf-8") == unit_text:
            return False
        unit_path.write_text(unit_text, encoding="utf-8")
        run(["systemctl", "daemon-reload"])
        return True

    @property
    def is_installed(self) -> bool:
        """Whether the binary is on the box."""
        return CLIPROXY_BINARY_PATH.is_file()

    def probe(self, *, port: int, client_key: str | None) -> tuple[bool, str]:
        """Ask the running gateway for its model list.

        Args:
            port: Where it listens.
            client_key: A key to authenticate with, when one exists.

        Returns:
            Whether it answered, and the served model names or the failure.
        """
        if client_key is None:
            return False, "no client key to probe with"
        try:
            response = httpx.get(
                f"http://127.0.0.1:{port}/v1/models",
                headers={"x-api-key": client_key},
                timeout=PROBE_TIMEOUT_S,
            )
        except httpx.HTTPError as error:
            return False, str(error)
        if not response.is_success:
            return False, f"answered {response.status_code}"
        try:
            names = [entry.get("id", "") for entry in response.json().get("data", [])]
        except ValueError:
            return False, "answered with something that is not JSON"
        return True, ", ".join(name for name in names if name) or "no models served"

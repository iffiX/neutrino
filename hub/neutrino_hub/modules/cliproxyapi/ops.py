"""Making the AI gateway's configuration true on the box.

Not pure: writes the generated file, restarts the unit, and probes the
running service.
"""

import hashlib
import os
import tempfile
from pathlib import Path

import httpx

from neutrino_hub.system.constants import SYSTEM_SYSTEMD_DIR
from neutrino_hub.utils import constants
from neutrino_hub.utils.constants import UTILS_GENERATED_DIR
from neutrino_hub.utils.json_file import read_config, write_config, write_generated
from neutrino_hub.utils.subprocess_run import run

from neutrino_hub.modules.cliproxyapi.config import CliproxyApiConfig
from neutrino_hub.modules.cliproxyapi.constants import (
    CLIPROXYAPI_AUTH_RELATIVE,
    CLIPROXYAPI_BINARY_PATH,
    CLIPROXYAPI_GENERATED_NAME,
    CLIPROXYAPI_SERVED_FINGERPRINT_RELATIVE,
    CLIPROXYAPI_UNIT,
)
from neutrino_hub.modules.cliproxyapi.management_key import (
    read_management_key,
    resolve_management_key,
)
from neutrino_hub.modules.cliproxyapi.renderer import CliproxyApiConfigRenderer
from neutrino_hub.modules.ai.registry import AiProviderRegistry

CLIPROXYAPI_CONFIG_PATH = "cliproxyapi/cliproxyapi.json"
PROBE_TIMEOUT_S = 5


def load_config() -> CliproxyApiConfig:
    """Read the stored settings, empty defaults when the file is missing.

    Returns:
        The parsed configuration.
    """
    try:
        return CliproxyApiConfig.from_dict(read_config(CLIPROXYAPI_CONFIG_PATH))
    except FileNotFoundError:
        return CliproxyApiConfig()


def save_config(config: CliproxyApiConfig) -> None:
    """Write the settings back.

    Args:
        config: The configuration to store.
    """
    write_config(CLIPROXYAPI_CONFIG_PATH, config.to_dict())


def read_served_fingerprint() -> str:
    """Read the fingerprint of the YAML the last apply handed the gateway.

    Returns:
        The stored sha256 hex digest, or empty when no apply has recorded one.
    """
    try:
        return _fingerprint_path().read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def write_served_fingerprint(rendered: str) -> None:
    """Record the sha256 of the YAML an apply has just written.

    Args:
        rendered: The text the applier wrote, before the gateway reads it.

    Raises:
        OSError: If the state file cannot be written.
    """
    path = _fingerprint_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, staged = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(fingerprint_of(rendered) + "\n")
        os.chmod(staged, 0o600)
        os.replace(staged, path)
    except BaseException:
        Path(staged).unlink(missing_ok=True)
        raise


def fingerprint_of(rendered: str) -> str:
    """The sha256 hex digest of a rendered configuration.

    Args:
        rendered: The rendered YAML.

    Returns:
        The digest.
    """
    return hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def ensure_auth_dir() -> Path:
    """Make the directory the gateway keeps signed-in accounts in.

    The token files are state, not configuration: they hold live provider
    credentials, they are never rendered from ``config/`` and a backup does
    not carry them.

    Returns:
        The directory, readable by root alone.

    Raises:
        OSError: If it cannot be created.
    """
    path = constants.UTILS_STATE_ROOT / CLIPROXYAPI_AUTH_RELATIVE
    path.mkdir(parents=True, exist_ok=True)
    path.chmod(0o700)
    return path


def _fingerprint_path() -> Path:
    # Resolved per call, against the state root as it is right now.
    return constants.UTILS_STATE_ROOT / CLIPROXYAPI_SERVED_FINGERPRINT_RELATIVE


class CliproxyApiConfigApplier:
    """Renders the YAML and restarts the service to pick it up."""

    def apply(self) -> str:
        """Render from the stored state and restart the gateway.

        Returns:
            A one-line summary of what happened.

        Raises:
            ValueError: If the stored settings do not validate, or a provider's
                or a client's sealed key does not open.
        """
        rendered, enabled = self._render()
        ensure_auth_dir()
        write_generated(
            UTILS_GENERATED_DIR / CLIPROXYAPI_GENERATED_NAME, rendered, mode=0o600
        )
        write_served_fingerprint(rendered)
        if not self.is_installed:
            return "rendered; the service is not installed yet"
        run(["systemctl", "restart", CLIPROXYAPI_UNIT])
        return f"applied with {enabled} provider(s) and restarted"

    def refresh_unit(self, unit_text: str) -> bool:
        """Install or update the systemd unit, telling whether it changed.

        Args:
            unit_text: The packaged unit's content.

        Returns:
            Whether anything was written.
        """
        unit_path = SYSTEM_SYSTEMD_DIR / CLIPROXYAPI_UNIT
        if unit_path.is_file() and unit_path.read_text(encoding="utf-8") == unit_text:
            return False
        unit_path.write_text(unit_text, encoding="utf-8")
        run(["systemctl", "daemon-reload"])
        return True

    @property
    def is_installed(self) -> bool:
        """Whether the binary is on the box."""
        return CLIPROXYAPI_BINARY_PATH.is_file()

    @property
    def is_serving_stale(self) -> bool:
        """Whether the gateway is running on something the stored state left behind.

        The fingerprint is taken of the text the applier wrote, not of the file
        as it is later found: the gateway rewrites its own copy to replace the
        management key with a bcrypt hash of it, and that rewrite is not a
        change anybody made. A box that has never applied, one whose render no
        longer matches, and one whose render fails all count as stale; a box
        with no gateway installed never does.
        """
        if not self.is_installed:
            return False
        try:
            rendered, _ = self._render()
        except ValueError:
            return True
        return fingerprint_of(rendered) != read_served_fingerprint()

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

    def render_with_stored_key(self) -> str:
        """Render with the key already on the box, for a dry run.

        Returns:
            The text an apply would write, given the working key as it is —
            a dry run must not generate one.

        Raises:
            ValueError: If the stored settings do not validate, or a provider's
                or a client's sealed key does not open.
        """
        rendered, _ = self._render(management_key=read_management_key())
        return rendered

    def _render(self, *, management_key: str | None = None) -> tuple[str, int]:
        """Render the YAML from the stored state.

        Args:
            management_key: The key to render with; None resolves it, which
                generates one on first need.

        Returns:
            The text an apply writes right now, and how many providers it
            carries a key for.

        Raises:
            ValueError: If the stored settings do not validate, or a provider's
                or a client's sealed key does not open.
        """
        config = load_config()
        config.validate()
        registry = AiProviderRegistry()
        providers = registry.list_records()
        api_keys = {
            provider.id: registry.open_api_key(provider)
            for provider in providers
            if provider.is_enabled
        }
        if management_key is None:
            management_key = resolve_management_key()
        rendered = CliproxyApiConfigRenderer(
            config=config,
            providers=providers,
            api_keys=api_keys,
            client_keys=[key.open_key() for key in config.client_keys],
            management_key=management_key,
        ).render()
        return rendered, sum(1 for key in api_keys.values() if key)

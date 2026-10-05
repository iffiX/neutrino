"""Making the AI gateway's configuration true on the box.

Not pure: writes the generated file, restarts the unit, and probes the
running service. On macOS and Windows the gateway is a child of the hub's one
service, restarted through the process controller. A change of keys alone is
written into the served file in place: the gateway watches that file and
reloads it without a restart, so no request in flight is cut.
"""

import hashlib
import os
import tempfile
import time
from pathlib import Path

import httpx

from neutrino_hub.platforms.detect import is_linux, process_controller
from neutrino_hub.system.constants import SYSTEM_SYSTEMD_DIR
from neutrino_hub.utils import constants
from neutrino_hub.utils.constants import UTILS_GENERATED_DIR
from neutrino_hub.utils.json_file import (
    read_config,
    rewrite_generated,
    write_config,
    write_generated,
)
from neutrino_hub.utils.subprocess_run import run

from neutrino_hub.modules.cliproxyapi.config import (
    CliproxyApiClientKey,
    CliproxyApiConfig,
)
from neutrino_hub.modules.cliproxyapi.constants import (
    CLIPROXYAPI_AUTH_RELATIVE,
    CLIPROXYAPI_BINARY_PATH,
    CLIPROXYAPI_GENERATED_NAME,
    CLIPROXYAPI_HUB_KEY_NAME,
    CLIPROXYAPI_KEY_REFUSED_STATUSES,
    CLIPROXYAPI_RELOAD_POLL_S,
    CLIPROXYAPI_RELOAD_WAIT_S,
    CLIPROXYAPI_RESTART_WAIT_S,
    CLIPROXYAPI_SERVED_FINGERPRINT_RELATIVE,
    CLIPROXYAPI_SERVED_MODELS_TTL_S,
    CLIPROXYAPI_SUPERVISED_NAME,
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
    """Renders the YAML and hands it to the gateway: a restart for a whole
    apply, a reload in place for a change of keys."""

    def apply(self) -> str:
        """Render from the stored state and restart the gateway.

        Returns:
            A one-line summary of what happened.

        Raises:
            ValueError: If the stored settings do not validate, or a provider's
                or a client's sealed key does not open.
        """
        self._ensure_hub_key()
        rendered, enabled = self._render()
        ensure_auth_dir()
        write_generated(
            UTILS_GENERATED_DIR / CLIPROXYAPI_GENERATED_NAME, rendered, mode=0o600
        )
        write_served_fingerprint(rendered)
        if not self.is_installed:
            return "rendered; the service is not installed yet"
        self._restart()
        return f"applied with {enabled} provider(s) and restarted"

    def apply_keys(self, *, new_key: "str | None" = None) -> str:
        """Hand the running gateway a changed set of keys without a restart.

        The render is written into the served file in place, which the
        gateway reloads by itself. A render equal to the one served writes
        nothing. With ``new_key``, the call returns once the gateway accepts
        that key; when it does not within ``CLIPROXYAPI_RELOAD_WAIT_S``, the
        gateway is restarted and the call returns once it listens again, or
        after ``CLIPROXYAPI_RESTART_WAIT_S``.

        Args:
            new_key: A key the change adds, which the gateway must accept
                before the call returns; None for a change that adds none.

        Returns:
            A one-line summary of what happened.

        Raises:
            ValueError: If the stored settings do not validate, or a provider's
                or a client's sealed key does not open.
        """
        self._ensure_hub_key()
        rendered, _ = self._render()
        served_path = UTILS_GENERATED_DIR / CLIPROXYAPI_GENERATED_NAME
        if not self.is_installed or not served_path.is_file():
            return self.apply()
        if fingerprint_of(rendered) == read_served_fingerprint():
            return "unchanged"
        rewrite_generated(served_path, rendered, mode=0o600)
        write_served_fingerprint(rendered)
        if new_key is None:
            return "reloaded"
        port = load_config().listen_port
        if self._wait(port, new_key, CLIPROXYAPI_RELOAD_WAIT_S, is_key_awaited=True):
            return "reloaded"
        self._restart()
        self._wait(port, new_key, CLIPROXYAPI_RESTART_WAIT_S, is_key_awaited=False)
        return "restarted"

    def _wait(
        self, port: int, key: str, timeout_s: float, *, is_key_awaited: bool
    ) -> bool:
        """Ask the gateway until it answers, or accepts the key, or time runs out.

        Args:
            port: Where it listens.
            key: The key the probe carries.
            timeout_s: How long to keep asking.
            is_key_awaited: Whether only an answer that accepts the key ends
                the wait; otherwise any answer does.

        Returns:
            Whether the wait ended on such an answer.
        """
        deadline = time.monotonic() + timeout_s
        while True:
            is_answered, failure, _ = self.probe(port=port, client_key=key)
            code = (failure or {}).get("code", "")
            status = (failure or {}).get("params", {}).get("status")
            if is_answered or (
                code == "gateway_probe_status"
                and (
                    not is_key_awaited or status not in CLIPROXYAPI_KEY_REFUSED_STATUSES
                )
            ):
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(CLIPROXYAPI_RELOAD_POLL_S)

    @staticmethod
    def _restart() -> None:
        """Restart the gateway: its unit on Linux, its supervised child elsewhere."""
        if is_linux():
            run(["systemctl", "restart", CLIPROXYAPI_UNIT])
        else:
            process_controller().restart(CLIPROXYAPI_SUPERVISED_NAME)

    @staticmethod
    def _ensure_hub_key() -> None:
        """Mint the hub's own gateway key when the stored state holds none.

        Raises:
            VaultLockedError: If there is no data key to seal it under.
        """
        config = load_config()
        if config.hub_key is not None:
            return
        config.hub_key = CliproxyApiClientKey.generated(CLIPROXYAPI_HUB_KEY_NAME)
        save_config(config)

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

    def probe(
        self, *, port: int, client_key: str | None
    ) -> tuple[bool, dict | None, list[str]]:
        """Ask the running gateway for its model list.

        Args:
            port: Where it listens.
            client_key: A key to authenticate with, when one exists.

        Returns:
            Whether it answered; the failure or the empty list as
            ``{code, params}``, None when models are served; and the served
            model names.
        """
        if client_key is None:
            return False, {"code": "gateway_no_probe_key", "params": {}}, []
        try:
            response = httpx.get(
                f"http://127.0.0.1:{port}/v1/models",
                headers={"x-api-key": client_key},
                timeout=PROBE_TIMEOUT_S,
            )
        except httpx.HTTPError:
            return False, {"code": "gateway_unreachable", "params": {}}, []
        if not response.is_success:
            return (
                False,
                {
                    "code": "gateway_probe_status",
                    "params": {"status": response.status_code},
                },
                [],
            )
        try:
            names = [entry.get("id", "") for entry in response.json().get("data", [])]
        except ValueError:
            return False, {"code": "gateway_probe_unreadable", "params": {}}, []
        # Sorted, since the gateway lists them in the order its providers
        # registered, and a person picking one reads them by name.
        served = sorted(name for name in names if name)
        if not served:
            return True, {"code": "gateway_no_models", "params": {}}, served
        return True, None, served

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
            client_keys=[
                key.open_key()
                for key in [*config.client_keys, config.hub_key]
                if key is not None
            ],
            management_key=management_key,
        ).render()
        return rendered, sum(1 for key in api_keys.values() if key)


class CliproxyApiServedModelCache:
    """The gateway's served model names, probed and kept for a short while.

    Heartbeats answer with the first served name, and a fleet beats every few
    seconds; the cache keeps that from asking the gateway on every beat.
    """

    def __init__(self):
        self._models: list[str] = []
        self._is_answered = False
        # None, not zero: `time.monotonic()` counts from boot on Linux, and a
        # panel started early in one would read the cache as fresh.
        self._probed_at: float | None = None

    def served(self, *, port: int, client_key: str) -> tuple[bool, list[str]]:
        """Whether the gateway answered and what it serves, re-probed when stale.

        Args:
            port: Where the gateway listens.
            client_key: A key to authenticate the probe with.

        Returns:
            ``(is_answered, models)``; the list is empty when nothing is
            served or the gateway does not answer.
        """
        if (
            self._probed_at is None
            or time.monotonic() - self._probed_at > CLIPROXYAPI_SERVED_MODELS_TTL_S
        ):
            self._is_answered, _, self._models = CliproxyApiConfigApplier().probe(
                port=port, client_key=client_key
            )
            self._probed_at = time.monotonic()
        return self._is_answered, list(self._models)

    def first_model(self, *, port: int, client_key: str) -> str:
        """The first model the gateway serves, re-probed only when stale.

        Args:
            port: Where the gateway listens.
            client_key: A key to authenticate the probe with.

        Returns:
            The first served model name, or empty when none is served or the
            gateway does not answer.
        """
        _, models = self.served(port=port, client_key=client_key)
        return models[0] if models else ""

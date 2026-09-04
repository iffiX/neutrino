"""Polling the AI gateway's usage queue into the persisted store.

The gateway's management API hands out per-request usage records exactly
once — reading the queue empties it — so one collector in the panel process
is the whole pipeline. Each poll maps the records' client key, upstream key
and credential handle to the ids the panel knows, folds them into the store,
and everything that shows usage reads the store rather than the gateway.
"""

import logging
import threading

import httpx

from neutrino_hub.modules.ai.registry import AiProviderRegistry
from neutrino_hub.modules.cliproxyapi.accounts import (
    CliproxyApiAccountClient,
    CliproxyApiAccountError,
)
from neutrino_hub.modules.cliproxyapi.constants import (
    CLIPROXYAPI_USAGE_POLL_INTERVAL_S,
    CLIPROXYAPI_USAGE_QUEUE_COUNT,
)
from neutrino_hub.modules.cliproxyapi.management_key import read_management_key
from neutrino_hub.modules.cliproxyapi.ops import load_config
from neutrino_hub.modules.cliproxyapi.usage_store import CliproxyApiUsageStore
from neutrino_hub.modules.credentials.vault import VaultError

LOGGER = logging.getLogger(__name__)

USAGE_QUEUE_PATH = "/v0/management/usage-queue"
POLL_TIMEOUT_S = 10


class PanelUsageCollector:
    """Pops the usage queue on an interval and folds it into the store."""

    def __init__(
        self,
        *,
        store: CliproxyApiUsageStore | None = None,
        poll_interval_s: float = CLIPROXYAPI_USAGE_POLL_INTERVAL_S,
    ):
        """
        Args:
            store: The store polls land in; None uses the state-root store.
            poll_interval_s: Seconds between polls.
        """
        self._store = store or CliproxyApiUsageStore()
        self._poll_interval_s = poll_interval_s
        self._is_stopped = threading.Event()
        self._thread: threading.Thread | None = None
        # The last resolvable upstream-key map, kept across a locked vault so
        # records keep landing on their providers instead of on nothing. The
        # account map is kept across an unreachable gateway for the same
        # reason.
        self._provider_ids: dict[str, str] = {}
        self._account_ids: dict[str, str] = {}

    def start(self) -> None:
        """Run the poll loop on a daemon thread; a second start is a no-op."""
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._loop, name="cliproxyapi_usage", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        """Stop the loop; the poll in flight finishes."""
        self._is_stopped.set()

    def poll_once(self) -> int:
        """Pop the queue once and fold what it held into the store.

        Returns:
            How many records were folded. Zero covers every quiet failure —
            no management key, a locked vault, the gateway down or refusing,
            nothing queued — because the next poll simply tries again.
        """
        management_key = read_management_key()
        if not management_key:
            return 0
        try:
            config = load_config()
            key_ids = {key.open_key(): key.id for key in config.client_keys}
        except (ValueError, VaultError):
            return 0
        try:
            response = httpx.get(
                f"http://127.0.0.1:{config.listen_port}{USAGE_QUEUE_PATH}",
                params={"count": CLIPROXYAPI_USAGE_QUEUE_COUNT},
                headers={"authorization": f"Bearer {management_key}"},
                timeout=POLL_TIMEOUT_S,
            )
        except httpx.HTTPError:
            return 0
        if not response.is_success:
            return 0
        try:
            records = response.json()
        except ValueError:
            return 0
        if not isinstance(records, list) or not records:
            return 0
        self._refresh_provider_ids()
        self._refresh_account_ids(
            port=config.listen_port, management_key=management_key
        )
        return self._store.ingest(
            records,
            key_ids=key_ids,
            key_names={key.id: key.name for key in config.client_keys},
            provider_ids=self._provider_ids,
            account_ids=self._account_ids,
        )

    def _refresh_provider_ids(self) -> None:
        registry = AiProviderRegistry()
        mapping = {}
        for record in registry.list_records():
            if not record.is_enabled or not record.secret_id:
                continue
            try:
                value = registry.open_api_key(record)
            except VaultError:
                return
            if value:
                mapping[value] = record.id
        self._provider_ids = mapping

    def _refresh_account_ids(self, *, port: int, management_key: str) -> None:
        """Map each account's credential handle to the token file naming it.

        Args:
            port: Where the gateway listens.
            management_key: The key that unlocks the auth-file list.
        """
        try:
            accounts = CliproxyApiAccountClient(
                port=port, management_key=management_key
            ).list_accounts()
        except CliproxyApiAccountError:
            return
        self._account_ids = {
            account.auth_index: account.name
            for account in accounts
            if account.auth_index and account.name
        }

    def _loop(self) -> None:
        while not self._is_stopped.wait(self._poll_interval_s):
            try:
                self.poll_once()
            except Exception:
                LOGGER.exception("usage poll failed")

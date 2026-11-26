"""Model prices: the list read from models.dev, the prices a person set, and each record's cost.

A price is what a vendor charges for a million tokens of one model, as four
numbers: input, output, cache read and cache write, in USD. The hub keeps
the models of the providers its vendors and logins are priced at, reads the
list once a day, refuses a download that is cut, emptied or reshaped, and
keeps the last good copy under the state root beside the snapshot the
package carries; the copy in force is the later of the two. A person sets a
served name's input and output price, in USD or CNY. A record's cost is
computed as it is folded in, from its token breakdown and the price in
force (hub_components/ai.md, "Prices", "A price a person sets", "Cost").

The checks, the lookup and the cost are pure. The reads and writes of the
files are the functions here, and the download is :func:`download_prices`.
"""

import json
import logging
import math
import operator
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from neutrino_hub.modules.ai.constants import (
    AI_CHARGE_API_VALUE,
    AI_CHARGE_COST,
    AI_CHARGE_NONE,
    AI_CHARGE_UNPRICED,
    AI_LOGIN_PRICE_PROVIDERS,
    AI_PRICE_CURRENCIES,
    AI_PRICE_DECIMALS,
    AI_PRICE_DEFAULT_CURRENCY,
    AI_PRICE_FIELDS,
    AI_PRICE_MAX,
    AI_PRICE_MIN,
    AI_PRICED_QUALITY,
    AI_PRICES_LIMIT_BYTES,
    AI_PRICES_MIN_MODELS,
    AI_PRICES_MIN_SNAPSHOT_RATIO,
    AI_PRICES_PATH,
    AI_PRICES_READ_TIMEOUT_S,
    AI_PRICES_SNAPSHOT_PATH,
    AI_PRICES_URL,
)
from neutrino_hub.modules.ai.vendors import endpoint_of, price_providers
from neutrino_hub.modules.cliproxyapi.constants import CLIPROXYAPI_MODEL_PRICES_RELATIVE
from neutrino_hub.utils import constants
from neutrino_hub.utils.constants import UTILS_FETCH_HEADERS
from neutrino_hub.utils.json_file import read_config, write_config, write_generated
from neutrino_hub.utils.tls_trust import public_ssl_context

LOGGER = logging.getLogger(__name__)

# What a read of models.dev ends in.
PRICES_WRITTEN = "written"
PRICES_REFUSED = "refused"
PRICES_FAILED = "failed"
TIME_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
# The unit a record's amount is rounded to: one millionth of its currency.
WHOLE = Decimal(1)


@dataclass(frozen=True)
class AiRecordCharge:
    """What one record adds to its cell.

    Attributes:
        kind: ``cost``, ``api_value``, ``unpriced`` or ``none``.
        currency: ``USD`` or ``CNY`` for a cost or an API value, else empty.
        amount: Millionths of the currency, 0 unless priced.
    """

    kind: str
    currency: str = ""
    amount: int = 0


def kept_providers(vendors: list) -> set:
    """The models.dev providers the hub prices with: each endpoint's, and each login's.

    Args:
        vendors: The preset table.

    Returns:
        The providers' ids.
    """
    return price_providers(vendors) | set(AI_LOGIN_PRICE_PROVIDERS.values())


def kept_prices(document: dict, providers) -> dict:
    """The four prices of each model of the providers the hub prices with.

    Args:
        document: The models.dev list, ``{<provider>: {models: {<model id>:
            {cost}}}}``.
        providers: The models.dev providers kept.

    Returns:
        ``{<provider>: {<model id>: {input, output, cache_read,
        cache_write}}}``, a cache price models.dev does not give left out.
        A model with no input or output price, or holding a price that is not
        a number of at least 0, is dropped.
    """
    kept = {}
    for provider in sorted(providers):
        entry = document.get(provider)
        models = entry.get("models") if isinstance(entry, dict) else None
        if not isinstance(models, dict):
            continue
        priced = {}
        for model_id, model in models.items():
            cost = model.get("cost") if isinstance(model, dict) else None
            price = _model_price(cost)
            if price is not None:
                priced[str(model_id)] = price
        if priced:
            kept[provider] = priced
    return kept


def priced_count(providers: dict) -> int:
    """How many priced models a kept list holds.

    Args:
        providers: ``{<provider>: {<model id>: prices}}``.

    Returns:
        The count over every provider.
    """
    return sum(len(models) for models in providers.values())


def checked_prices(
    body: bytes, *, providers, snapshot_count: int, fetched_at: str
) -> tuple:
    """A downloaded list, kept down to the hub's providers, or why it is refused.

    Args:
        body: The download, up to one byte past the limit.
        providers: The models.dev providers kept.
        snapshot_count: The priced models of the carried snapshot.
        fetched_at: When the download was made.

    Returns:
        ``(document, reason, count)``: the list to store and an empty reason,
        or None and the reason it is refused; ``count`` the priced models
        kept, 0 where none were counted.
    """
    if len(body) > AI_PRICES_LIMIT_BYTES:
        return None, f"larger than {AI_PRICES_LIMIT_BYTES} bytes", 0
    try:
        held = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None, "not JSON", 0
    if not isinstance(held, dict):
        return None, "no object at the top level", 0
    kept = kept_prices(held, providers)
    count = priced_count(kept)
    if count < AI_PRICES_MIN_MODELS:
        return None, f"fewer than {AI_PRICES_MIN_MODELS} priced models", count
    if count < snapshot_count * AI_PRICES_MIN_SNAPSHOT_RATIO:
        return None, "fewer than half the snapshot's priced models", count
    return {"fetched_at": fetched_at, "providers": kept}, "", count


def read_price_list(path) -> "dict | None":
    """One stored price list.

    Args:
        path: The file.

    Returns:
        ``{fetched_at, providers}``; None while it is absent or does not
        read as one.
    """
    try:
        with open(path, encoding="utf-8") as stream:
            held = json.load(stream)
    except (OSError, ValueError):
        return None
    if not isinstance(held, dict) or not isinstance(held.get("providers"), dict):
        return None
    return {
        "fetched_at": str(held.get("fetched_at", "") or ""),
        "providers": {
            str(provider): {
                str(model): price
                for model, price in models.items()
                if isinstance(price, dict)
            }
            for provider, models in held["providers"].items()
            if isinstance(models, dict)
        },
    }


def read_snapshot() -> "dict | None":
    """The price list the package carries.

    Returns:
        ``{fetched_at, providers}``; None while it does not read.
    """
    return read_price_list(AI_PRICES_SNAPSHOT_PATH)


def read_stored_prices() -> "dict | None":
    """The last download that passed the checks.

    Returns:
        ``{fetched_at, providers}``; None while none is stored.
    """
    return read_price_list(_stored_path())


def prices_in_force() -> dict:
    """The copy in force: the later of the stored download and the snapshot.

    Returns:
        ``{fetched_at, providers}``, empty while neither reads.
    """
    found = [held for held in (read_stored_prices(), read_snapshot()) if held]
    if not found:
        return {"fetched_at": "", "providers": {}}
    return max(found, key=operator.itemgetter("fetched_at"))


def download_prices(*, url: str = AI_PRICES_URL, opener=None) -> bytes:
    """Read the models.dev list, as the hub's own connection.

    Args:
        url: Where the list is served.
        opener: Called with ``(request, timeout)``, returns the answer; None
            opens over the network.

    Returns:
        The answer's bytes, at most one byte past the limit.

    Raises:
        OSError: If the list could not be read.
    """
    request = urllib.request.Request(url, headers=dict(UTILS_FETCH_HEADERS))
    open_url = opener or _open_url
    with open_url(request, AI_PRICES_READ_TIMEOUT_S) as response:
        return response.read(AI_PRICES_LIMIT_BYTES + 1)


def refresh_model_prices(*, providers, download=download_prices, now=None) -> str:
    """Read the models.dev list once, and store it when it passes the checks.

    Args:
        providers: The models.dev providers kept.
        download: Reads the list, as :func:`download_prices`.
        now: The moment of the read; None is the real clock.

    Returns:
        ``written``, ``refused`` (the copy in force kept, one log line with
        the reason and the counts) or ``failed`` (the read did not complete,
        or the store was not written).
    """
    moment = now or datetime.now(timezone.utc)
    try:
        body = download()
    except OSError as error:
        LOGGER.info("the price list was not read from models.dev: %s", error)
        return PRICES_FAILED
    snapshot = read_snapshot() or {"providers": {}}
    snapshot_count = priced_count(snapshot["providers"])
    document, reason, count = checked_prices(
        body,
        providers=providers,
        snapshot_count=snapshot_count,
        fetched_at=moment.strftime(TIME_FORMAT),
    )
    if document is None:
        LOGGER.warning(
            "the price list from models.dev was refused: %s; %d bytes, %d priced "
            "models kept, %d in the snapshot",
            reason,
            len(body),
            count,
            snapshot_count,
        )
        return PRICES_REFUSED
    try:
        write_generated(
            _stored_path(), json.dumps(document, sort_keys=True) + "\n", mode=0o600
        )
    except OSError as error:
        LOGGER.warning("the price list was not stored: %s", error)
        return PRICES_FAILED
    return PRICES_WRITTEN


def seconds_until_due(fetched_at: str, *, interval_s: float, now=None) -> float:
    """How long until the copy in force is a read's interval old.

    Args:
        fetched_at: When the copy in force was made.
        interval_s: The interval between reads.
        now: The moment asked about; None is the real clock.

    Returns:
        Seconds, 0 when it is due now or names no time.
    """
    try:
        made = datetime.strptime(fetched_at, TIME_FORMAT).replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return 0.0
    moment = now or datetime.now(timezone.utc)
    return max(0.0, interval_s - (moment - made).total_seconds())


def next_read_wait_s(outcome: str, *, interval_s: float, retry_s: float) -> float:
    """How long after a read the next one waits.

    Args:
        outcome: What the read ended in.
        interval_s: The interval between reads.
        retry_s: The wait after a read that failed.

    Returns:
        ``retry_s`` after a read that failed, since the network comes back;
        ``interval_s`` after a written or a refused one, since a refused file
        is models.dev's.
    """
    return retry_s if outcome == PRICES_FAILED else interval_s


def read_set_prices() -> dict:
    """The prices a person set, by served name.

    Returns:
        Name to ``{input, output, currency}``; empty while the file is
        absent, does not read, or holds none. An entry that is not a valid
        price is left out.
    """
    try:
        held = read_config(AI_PRICES_PATH)
    except (FileNotFoundError, ValueError):
        return {}
    prices = held.get("prices") if isinstance(held, dict) else None
    if not isinstance(prices, dict):
        return {}
    found = {}
    for name, price in prices.items():
        if isinstance(price, dict) and price_refusal(price) is None:
            found[str(name)] = {
                "input": price["input"],
                "output": price["output"],
                "currency": price["currency"],
            }
    return found


def write_set_prices(prices: dict) -> None:
    """Store the prices a person set.

    Args:
        prices: Name to ``{input, output, currency}``.
    """
    write_config(AI_PRICES_PATH, {"prices": dict(sorted(prices.items()))})


def price_refusal(price: dict) -> "tuple | None":
    """Why a set price is refused, if it is.

    Args:
        price: ``{input, output, currency}``.

    Returns:
        ``("price_invalid", number)`` for a number outside the range or with
        too many decimals, ``("currency_invalid", currency)`` for a currency
        other than USD and CNY; None for a valid price.
    """
    for field in ("input", "output"):
        value = price.get(field)
        if not _is_settable(value):
            return "price_invalid", value
    currency = price.get("currency")
    if currency not in AI_PRICE_CURRENCIES:
        return "currency_invalid", currency
    return None


def is_default_price(price: dict, default: "dict | None") -> bool:
    """Whether a set price is the default, in the default's currency.

    Args:
        price: ``{input, output, currency}``.
        default: The name's default price; None while it has none.

    Returns:
        True when the two numbers and the currency equal the default's.
    """
    if default is None:
        return False
    return (
        price["currency"] == default["currency"]
        and Decimal(str(price["input"])) == Decimal(str(default["input"]))
        and Decimal(str(price["output"])) == Decimal(str(default["output"]))
    )


class AiPriceTable:
    """The copy in force, looked up by models.dev provider and model id."""

    def __init__(self, providers: dict):
        """
        Args:
            providers: ``{<provider>: {<model id>: {input, output,
                cache_read, cache_write}}}``.
        """
        self._providers = {
            provider: {str(model).lower(): price for model, price in models.items()}
            for provider, models in providers.items()
        }

    def price(self, provider: str, model: str) -> "dict | None":
        """One model's models.dev price.

        Args:
            provider: The models.dev provider.
            model: The name the upstream serves, matched whole without case.

        Returns:
            ``{input, output, cache_read, cache_write}`` with a cache price
            absent where models.dev gives none; None for no price.
        """
        if not provider or not model:
            return None
        return self._providers.get(provider, {}).get(model.lower())


def source_price_provider(
    origin_is_account: bool, name: str, provider_record, endpoints: list
) -> str:
    """The models.dev provider one source of a name is priced at.

    Args:
        origin_is_account: Whether the source is an account.
        name: An account's login, as the gateway names its provider.
        provider_record: A stored provider's record, None for an account.
        endpoints: Every vendor endpoint.

    Returns:
        The provider's id, empty for none.
    """
    if origin_is_account:
        return AI_LOGIN_PRICE_PROVIDERS.get(name.lower(), "")
    if provider_record is None:
        return ""
    endpoint = endpoint_of(provider_record.kind, provider_record.base_url, endpoints)
    return endpoint.price_provider if endpoint is not None else ""


def default_price(sources: list, table: AiPriceTable) -> "dict | None":
    """A cloud name's default price: the first source in serving order models.dev prices.

    Args:
        sources: ``(price provider, upstream name)`` per source, the accounts
            first and then the stored providers in the list's order.
        table: The copy in force.

    Returns:
        ``{input, output, cache_read, cache_write, currency}`` with a cache
        price absent where models.dev gives none and ``currency`` USD; None
        while no source has one.
    """
    for provider, upstream in sources:
        price = table.price(provider, upstream)
        if price is not None:
            return {**price, "currency": AI_PRICE_DEFAULT_CURRENCY}
    return None


class AiRecordPricer:
    """Prices each queue record as the collector folds it in."""

    def __init__(
        self,
        *,
        table: AiPriceTable,
        set_prices: dict,
        providers: dict,
        accounts: dict,
        endpoints: list,
        ollama_providers=(),
        ollama_names=(),
    ):
        """
        Args:
            table: The copy in force.
            set_prices: The prices a person set, by served name.
            providers: Each stored provider's record, by id.
            accounts: Each account's login, as the gateway names its
                provider, by token file.
            endpoints: Every vendor endpoint.
            ollama_providers: The gateway's provider names of the providers
                generated from each machine's Ollama, as a record names them.
            ollama_names: The names a generated Ollama provider lists.
        """
        self._table = table
        self._set_prices = {
            str(name).lower(): price for name, price in set_prices.items()
        }
        self._providers = providers
        self._accounts = accounts
        self._endpoints = endpoints
        self._ollama_providers = {str(name).lower() for name in ollama_providers}
        self._ollama_names = {str(name).lower() for name in ollama_names}

    def charge(self, record: dict, upstream_id: str) -> AiRecordCharge:
        """What one record adds to its cell.

        Args:
            record: The queue record.
            upstream_id: The provider's id or the account's token file it
                was served by, empty when neither is known.

        Returns:
            Nothing for a generated Ollama provider's record; else its cost,
            or its API value for an account or a plan endpoint, or a count
            among the requests with no price.
        """
        if str(record.get("provider", "")).lower() in self._ollama_providers:
            return AiRecordCharge(kind=AI_CHARGE_NONE)
        model = str(record.get("model", "") or "")
        served = str(record.get("alias", "") or "") or model
        price_provider, is_value = self._upstream(upstream_id)
        price = self._price(price_provider, model, served)
        counts = _breakdown_counts(record.get("token_breakdown"))
        if price is None or counts is None:
            return AiRecordCharge(kind=AI_CHARGE_UNPRICED)
        amount = (
            counts["uncached"] * _decimal(price["input"])
            + counts["cache_read"] * _decimal(price["cache_read"])
            + counts["cache_write"] * _decimal(price["cache_write"])
            + counts["output"] * _decimal(price["output"])
        )
        return AiRecordCharge(
            kind=AI_CHARGE_API_VALUE if is_value else AI_CHARGE_COST,
            currency=price["currency"],
            amount=int(amount.quantize(WHOLE, rounding=ROUND_HALF_UP)),
        )

    def _upstream(self, upstream_id: str) -> tuple:
        """The models.dev provider an upstream is priced at, and whether its amount is an API value."""
        if upstream_id in self._providers:
            record = self._providers[upstream_id]
            endpoint = endpoint_of(record.kind, record.base_url, self._endpoints)
            if endpoint is None:
                return "", False
            return endpoint.price_provider, endpoint.is_plan
        if upstream_id in self._accounts:
            login = str(self._accounts[upstream_id] or "").lower()
            return AI_LOGIN_PRICE_PROVIDERS.get(login, ""), True
        return "", False

    def _price(self, price_provider: str, model: str, served: str) -> "dict | None":
        """The four prices and the currency a record is priced at, None for no price."""
        base = self._table.price(price_provider, model)
        held = None
        if served.lower() not in self._ollama_names:
            held = self._set_prices.get(served.lower())
        if held is not None:
            return {
                "input": held["input"],
                "output": held["output"],
                "cache_read": _scaled(held["input"], base, "cache_read"),
                "cache_write": _scaled(held["input"], base, "cache_write"),
                "currency": held["currency"],
            }
        if base is None:
            return None
        return {
            "input": base["input"],
            "output": base["output"],
            "cache_read": base.get("cache_read", base["input"]),
            "cache_write": base.get("cache_write", base["input"]),
            "currency": AI_PRICE_DEFAULT_CURRENCY,
        }


def _scaled(person_input, base: "dict | None", field: str):
    """A person's cache price: their input price times models.dev's ratio, or their input price."""
    if base is None or field not in base or not base["input"]:
        return person_input
    return _decimal(person_input) * _decimal(base[field]) / _decimal(base["input"])


def _breakdown_counts(breakdown) -> "dict | None":
    """A record's four counts from its v2 token breakdown, None when it cannot be priced."""
    if not isinstance(breakdown, dict):
        return None
    if breakdown.get("quality") != AI_PRICED_QUALITY:
        return None
    input_block = breakdown.get("input")
    output_block = breakdown.get("output")
    if not isinstance(input_block, dict) or not isinstance(output_block, dict):
        return None
    return {
        "uncached": _count(input_block.get("uncached_tokens")),
        "cache_read": _count(input_block.get("cache_read_tokens")),
        "cache_write": _count(input_block.get("cache_write_tokens")),
        "output": _count(output_block.get("total_tokens")),
    }


def _model_price(cost) -> "dict | None":
    """A models.dev cost's four prices, None for one that does not price the model."""
    if not isinstance(cost, dict):
        return None
    price = {}
    for field in AI_PRICE_FIELDS:
        if field not in cost:
            continue
        value = cost[field]
        if not _is_number(value) or value < 0:
            return None
        price[field] = value
    if "input" not in price or "output" not in price:
        return None
    return price


def _is_number(value) -> bool:
    """Whether a JSON value is a finite number."""
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
    )


def _is_settable(value) -> bool:
    """Whether a number is a price a person may set."""
    if not _is_number(value) or not AI_PRICE_MIN <= value <= AI_PRICE_MAX:
        return False
    return -Decimal(str(value)).as_tuple().exponent <= AI_PRICE_DECIMALS


def _decimal(value) -> Decimal:
    """A price or a ratio as an exact decimal."""
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _count(value) -> int:
    """A token count, 0 for anything that is not a whole number of at least 0."""
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(value, 0)


def _open_url(request: urllib.request.Request, timeout: float):
    """Open one request over the network, verifying the host's certificate."""
    return urllib.request.urlopen(
        request, timeout=timeout, context=public_ssl_context()
    )


def _stored_path():
    # Resolved per call, against the state root as it is right now.
    return constants.UTILS_STATE_ROOT / CLIPROXYAPI_MODEL_PRICES_RELATIVE

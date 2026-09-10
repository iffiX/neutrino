"""What a client may ask the hub over its socket, and how each is answered.

An ask is ``{type: "ask", id, kind, args}``; the answer carries the same
``id`` and either ``result`` or ``{code, params}``. Pure: the live shares
and the password reader come in as arguments.
"""

import hashlib
import json

from neutrino_hub.modules.clients.constants import (
    CLIENT_ASK_RDP_CONNECT,
    CLIENT_CODE_ASK_UNKNOWN,
    CLIENT_CODE_DISABLED,
    CLIENT_CODE_RDP_NOT_SHARED,
    CLIENT_CODE_SERVICE_UNKNOWN,
    CLIENT_RDP_SERVICE_PREFIX,
)


def catalog_frame(services: list, *, is_disabled: bool) -> dict:
    """The catalog as the client is handed it.

    Args:
        services: The typed entries resolved for this client.
        is_disabled: True hands an empty catalog.

    Returns:
        ``{type: "catalog", hash, services}``.
    """
    entries = [] if is_disabled else list(services)
    serialized = json.dumps(entries, sort_keys=True).encode("utf-8")
    return {
        "type": "catalog",
        "hash": hashlib.sha256(serialized).hexdigest()[:16],
        "services": entries,
    }


def answer_ask(ask: dict, *, is_disabled: bool, shares: list, seat_password_of) -> dict:
    """Answer one ask.

    Args:
        ask: The decoded frame.
        is_disabled: Whether the asking client is switched off.
        shares: The live :class:`DeviceShare` records.
        seat_password_of: Called with a device key; returns its seat
            password, empty when it has none.

    Returns:
        The answer frame, ``id`` included.
    """
    answer = {"type": "answer", "id": ask.get("id")}
    if is_disabled:
        return {**answer, "code": CLIENT_CODE_DISABLED, "params": {}}
    kind = str(ask.get("kind", "") or "")
    args = ask.get("args") if isinstance(ask.get("args"), dict) else {}
    if kind == CLIENT_ASK_RDP_CONNECT:
        return {**answer, **_rdp_connect(args, shares, seat_password_of)}
    return {**answer, "code": CLIENT_CODE_ASK_UNKNOWN, "params": {"kind": kind}}


def _rdp_connect(args: dict, shares: list, seat_password_of) -> dict:
    service_id = str(args.get("service_id", "") or "")
    if not service_id.startswith(CLIENT_RDP_SERVICE_PREFIX):
        return {
            "code": CLIENT_CODE_SERVICE_UNKNOWN,
            "params": {"service_id": service_id},
        }
    share_id = service_id[len(CLIENT_RDP_SERVICE_PREFIX) :]
    for share in shares:
        if share.share_id == share_id:
            return {
                "result": {
                    "host": share.host,
                    "port": share.port,
                    "password": seat_password_of(share.mac_address),
                }
            }
    return {"code": CLIENT_CODE_RDP_NOT_SHARED, "params": {"service_id": service_id}}

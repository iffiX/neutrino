"""Answering the transport for a Web share's visitors.

A guest reaches the agent port through WebRTC with a share's ticket. The
transport asks ``guest`` at its open record, passes its ``hello``, asks
``entry`` at each ``connect`` it opens and ``token`` at its ``service``
frame. Each is judged against the share now: the share, the entry, the
machine, the entry's publication and the share's guest, in that order
(protocol.md, "Web shares"). A refusal counts as no failed admission.
"""

import asyncio
import secrets
import time

from neutrino_hub.exceptions import AgentOfflineError, VaultLockedError
from neutrino_hub.modules.channel.admission import admit
from neutrino_hub.modules.channel.constants import (
    CHANNEL_CODE_KIND_UNKNOWN,
    CHANNEL_STREAM_CONNECT,
)
from neutrino_hub.modules.clients.constants import (
    CLIENT_CODE_PERMISSION_DENIED,
    CLIENT_CODE_SERVICE_UNKNOWN,
    CLIENT_PERMISSION_PANEL,
    WEB_SHARE_CODE_SHARE_UNKNOWN,
    WEB_SHARE_STATE_ACTIVE,
)
from neutrino_hub.modules.clients.permissions import entry_host
from neutrino_hub.modules.clients.services import entry_port, entry_protocol
from neutrino_hub.modules.clients.web_shares import (
    WebShareRegistry,
    guest_secret,
    share_state,
)
from neutrino_hub.modules.devices.constants import (
    DEVICE_FORWARDER_TOKEN_LIFETIME_S,
    DEVICE_FORWARDER_TOKEN_NONCE_BYTES,
    DEVICE_GUEST_LOGIN_GUEST_ACCOUNT,
    DEVICE_GUEST_LOGIN_RUN_ACCOUNT,
    DEVICE_HERMES_WEBUI_MODULE,
)
from neutrino_hub.modules.devices.desired_state import forwarder_token
from neutrino_hub.modules.devices.manifests import load_module_manifests
from neutrino_hub.modules.devices.module_table import module_row
from neutrino_hub.modules.services.constants import (
    SERVICES_SOURCE_DECLARED,
    SERVICES_TYPE_WEB,
)
from neutrino_hub.web.web_share_access import entry_guest_login, guests_reported


async def guest_answer(fields: dict) -> dict:
    """The answer to the ``guest`` question at a visitor's open record.

    Args:
        fields: ``{ticket, share, protocol, address, listener}``, ``share``
            being the ufrag the gate opened the data channel under.

    Returns:
        ``{binding_id}``, the share's id; or ``{code, params}``: the
        admission codes by protocol number, else ``share_unknown`` for a
        ufrag no live share holds or a ticket not that share's.
    """
    refusal = admit(_int(fields.get("protocol")))
    if refusal is not None:
        return refusal
    ufrag = str(fields.get("share", "") or "")
    ticket = str(fields.get("ticket", "") or "")
    share = await asyncio.to_thread(WebShareRegistry().find_by_ufrag, ufrag)
    if share is None or share.is_expired(time.time()) or not share.is_ticket(ticket):
        return _refusal(WEB_SHARE_CODE_SHARE_UNKNOWN, {})
    return {"binding_id": share.id}


def is_share_live(share_id: str) -> bool:
    """Whether a share is stored and has not expired."""
    share = WebShareRegistry().get(share_id)
    return share is not None and not share.is_expired(time.time())


async def guest_entry_answer(runtime, share_id: str, open_body: dict) -> dict:
    """The answer to an ``entry`` question for a visitor's stream.

    Args:
        runtime: The shared runtime.
        share_id: The share the guest session was admitted to.
        open_body: The open record's object.

    Returns:
        ``{kind, device_id, key, target}`` for a ``connect`` to the share's
        entry; or ``{code, params}``.
    """
    kind = str(open_body.get("kind", "") or "")
    if kind != CHANNEL_STREAM_CONNECT:
        return _refusal(CHANNEL_CODE_KIND_UNKNOWN, {"kind": kind})
    code, params, judged = await asyncio.to_thread(_judge, runtime, share_id, open_body)
    if code:
        return _refusal(code, params)
    share, raw = judged
    answer = {"kind": SERVICES_TYPE_WEB, "device_id": share.device_id, "key": ""}
    if raw.get("device_id"):
        agent = runtime.agent_sessions.get(str(raw["device_id"]))
        if agent is None:
            return _refusal(AgentOfflineError.code, {"device": str(raw["device_id"])})
        answer["target"] = {
            "session": agent.session_id,
            "open": {
                "kind": CHANNEL_STREAM_CONNECT,
                "port": entry_port(raw),
                "protocol": entry_protocol(raw),
            },
        }
        return answer
    if raw.get("source") == SERVICES_SOURCE_DECLARED:
        answer["target"] = {
            "address": entry_host(raw),
            "port": entry_port(raw),
            "protocol": entry_protocol(raw),
        }
        return answer
    return _refusal(CLIENT_CODE_SERVICE_UNKNOWN, {"service_id": share.entry_id})


async def guest_token_answer(runtime, share_id: str, frame: dict) -> dict:
    """The answer to a ``token`` question at a visitor's ``service`` frame.

    Args:
        runtime: The shared runtime.
        share_id: The share the guest session was admitted to.
        frame: The ``service`` frame.

    Returns:
        ``{params}``, the material the entry's ``guest_login`` gives; or
        ``{code, params}``.
    """
    code, params = await asyncio.to_thread(_material, runtime, share_id, frame)
    if code:
        return _refusal(code, params)
    return {"params": params}


def _judge(runtime, share_id: str, asked: dict) -> tuple:
    """Whether a visitor may reach what it asked for, in the order of the codes.

    Args:
        runtime: The shared runtime.
        share_id: The share.
        asked: The ``service`` frame or the ``connect`` open, ``{id}`` or
            ``{is_panel: true}``.

    Returns:
        ``(code, params, (share, raw))``: a refusal with None; or an empty
        code, empty params, the share and its entry as published.
    """
    share = WebShareRegistry().get(share_id)
    if share is None or share.is_expired(time.time()):
        return WEB_SHARE_CODE_SHARE_UNKNOWN, {}, None
    entries, _ = runtime.published_services.entries()
    if asked.get("is_panel") is True:
        return CLIENT_CODE_PERMISSION_DENIED, {"kind": CLIENT_PERMISSION_PANEL}, None
    entry_id = str(asked.get("id", "") or "")
    if entry_id != share.entry_id:
        named = next((entry for entry in entries if entry["id"] == entry_id), {})
        return (
            CLIENT_CODE_PERMISSION_DENIED,
            {"kind": str(named.get("type", "") or SERVICES_TYPE_WEB)},
            None,
        )
    if share.device_id and not runtime.agent_sessions.is_online(share.device_id):
        return AgentOfflineError.code, {"device": share.device_id}, None
    raw = next((entry for entry in entries if entry["id"] == share.entry_id), None)
    if raw is None:
        return CLIENT_CODE_SERVICE_UNKNOWN, {"service_id": share.entry_id}, None
    state, _, _ = share_state(
        share,
        is_published=True,
        is_online=True,
        guests_reported=guests_reported(runtime.agent_sessions.reports(), share),
    )
    if state != WEB_SHARE_STATE_ACTIVE:
        return CLIENT_CODE_SERVICE_UNKNOWN, {"service_id": share.entry_id}, None
    return "", {}, (share, raw)


def _material(runtime, share_id: str, frame: dict) -> tuple:
    """The material a visitor's ``service`` frame is handed, judged now.

    Returns:
        ``(code, params)``: empty material for ``app``; a ``{token}`` minted
        with the share's guest secret for ``guest_account``; for
        ``run_account`` the token a client gets for the entry; or a refusal,
        ``vault_locked`` when the secret does not open.
    """
    code, params, judged = _judge(runtime, share_id, frame)
    if code:
        return code, params
    share, raw = judged
    guest_login, module = entry_guest_login(raw, load_module_manifests())
    if guest_login == DEVICE_GUEST_LOGIN_GUEST_ACCOUNT:
        try:
            secret = guest_secret(share)
        except VaultLockedError:
            return VaultLockedError.code, {}
        if not secret:
            return VaultLockedError.code, {}
        token = forwarder_token(
            secret,
            expiry=int(time.time()) + DEVICE_FORWARDER_TOKEN_LIFETIME_S,
            nonce=secrets.token_bytes(DEVICE_FORWARDER_TOKEN_NONCE_BYTES),
        )
        return "", {"token": token}
    if guest_login == DEVICE_GUEST_LOGIN_RUN_ACCOUNT:
        token = _run_account_token(runtime, raw, module)
        if not token:
            return VaultLockedError.code, {}
        return "", {"token": token}
    return "", {}


def _run_account_token(runtime, raw: dict, module: str) -> str:
    """The token a client opens the entry with, empty when it does not open."""
    device_id = str(raw.get("device_id", "") or "")
    states = runtime.desired_states
    if module == DEVICE_HERMES_WEBUI_MODULE:
        return states.module_token(device_id, module)
    row = module_row(module)
    if not row.is_account_layer:
        return states.module_token(device_id, module)
    account = str((raw.get("description_params") or {}).get("account", "") or "")
    return states.instance_token(device_id, module, account)


def _int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _refusal(code: str, params: dict) -> dict:
    return {"code": code, "params": dict(params or {})}

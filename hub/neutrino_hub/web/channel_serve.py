"""The hub's side of the local channel: every question, event and frame.

The transport asks four questions and the hub's Python answers each from
its records: whose static key a knock named (``peer``), whether a ticket is
good and what binding it makes (``ticket``), where a stream goes and whether
the binding may open it (``entry``), and what material a ``service`` frame
is handed (``token``). The transport raises an event when a session opens
or ends and when an agent opens a stream the Python takes, ``log`` or
``package``, and it passes every other frame of an admitted session here:
``hello``, ``report``, ``leave``, a client's ``persist`` and
``stop_session``, an agent's ``reply`` (transport.md, "The hub's local
channel").

An agent's reports are recorded and its state offered once per connection;
a client's are recorded and its state pushed when the hashes differ. An
agent older than the hub whose own package was refused before the hub knew
its platform is sent ``reinstall`` once, when the report naming the platform
lands, unless it runs on the hub's own machine.
"""

import asyncio
import codecs
import functools
import hashlib
import json
import logging
import math
import time

from pydantic import ValidationError

from neutrino_hub import HUB_VERSION
from neutrino_hub.exceptions import (
    AgentArtifactFetchError,
    AgentOfflineError,
    DownloadFailedError,
    StreamRefusedError,
    TaskExitStatusError,
)
from neutrino_hub.modules.channel.admission import admit
from neutrino_hub.modules.channel.bindings import spend_ticket
from neutrino_hub.modules.channel.constants import (
    CHANNEL_CHUNK_BYTES,
    CHANNEL_CODE_ADMISSION_PAUSED,
    CHANNEL_CODE_BINDING_UNKNOWN,
    CHANNEL_CODE_CONTROL_UNAVAILABLE,
    CHANNEL_CODE_HELLO_INVALID,
    CHANNEL_CODE_ROLE_MISMATCH,
    CHANNEL_CODE_TICKET_SPENT,
    CHANNEL_COMMAND_MODULE_AGENT,
    CHANNEL_DEV_VERSION_SUFFIX,
    CHANNEL_EVENT_SESSION_END,
    CHANNEL_EVENT_SESSION_OPEN,
    CHANNEL_EVENT_STREAM,
    CHANNEL_FRAME_HELLO,
    CHANNEL_FRAME_LEAVE,
    CHANNEL_FRAME_LEFT,
    CHANNEL_FRAME_REPLY,
    CHANNEL_FRAME_REPORT,
    CHANNEL_FRAME_WELCOME,
    CHANNEL_PACKAGE_PLATFORM_POLL_S,
    CHANNEL_PACKAGE_PLATFORM_WAIT_S,
    CHANNEL_QUESTION_ENTRY,
    CHANNEL_QUESTION_GUEST,
    CHANNEL_QUESTION_PEER,
    CHANNEL_QUESTION_TICKET,
    CHANNEL_QUESTION_TOKEN,
    CHANNEL_ROLE_AGENT,
    CHANNEL_ROLE_CLIENT,
    CHANNEL_ROLE_GUEST,
    CHANNEL_ROLE_HUB,
    CHANNEL_STREAM_COMMAND,
    CHANNEL_STREAM_LOG,
    CHANNEL_STREAM_PACKAGE,
    CHANNEL_VERB_REINSTALL,
    PROTOCOL,
)
from neutrino_hub.modules.channel.sessions import (
    ChannelSession,
    version_of_software,
)
from neutrino_hub.modules.clients.ai_keys import revoke_client_key
from neutrino_hub.modules.clients.constants import WEB_SHARE_CODE_SHARE_UNKNOWN
from neutrino_hub.modules.clients.registry import ClientRegistry
from neutrino_hub.modules.clients.services import panel_material, service_material
from neutrino_hub.modules.devices.agent_module_cache import AgentModuleSendProgress
from neutrino_hub.modules.devices.agent_package import platform_family
from neutrino_hub.modules.devices.agent_reports import (
    record_hello,
    record_offline,
    record_report,
)
from neutrino_hub.modules.devices.manifests import load_module_manifests
from neutrino_hub.modules.devices.registry import DeviceRegistry
from neutrino_hub.modules.frp.constants import FRP_LOOPBACK_PORTS
from neutrino_hub.system.machine import machine_id
from neutrino_hub.utils.peer_address import unmapped
from neutrino_hub.utils.version_number import parse_version
from neutrino_hub.web import channel_state
from neutrino_hub.web.channel_entry import entry_answer
from neutrino_hub.web.channel_guest import (
    guest_answer,
    guest_entry_answer,
    guest_token_answer,
    is_share_live,
)
from neutrino_hub.web.channel_shell import SESSION_VERBS, relay_session_verb
from neutrino_hub.web.constants import (
    WEB_EVENT_CLIENTS,
    WEB_EVENT_DEVICE_REPORT,
    WEB_EVENT_DEVICES,
    WEB_EVENT_METRICS,
    WEB_TASK_LABEL_MODULE,
)
from neutrino_hub.web.identity import hub_id, hub_name
from neutrino_hub.web.models import ChannelHello, ChannelJoin
from neutrino_hub.web.panel_sign_in import SESSION_END_LEFT, end_client_panel_sessions
from neutrino_hub.web.web_share_access import push_shares

LOGGER = logging.getLogger(__name__)

# What a report has to change before the panel refetches the device list.
# Metrics are not among them: every report carries them, and they ride
# their own event to the tiles and the monitor.
REPORT_PANEL_SECTIONS = ("modules", "desktop", "error", "ai_tools")
ROLES = (CHANNEL_ROLE_AGENT, CHANNEL_ROLE_CLIENT)


class ChannelControlHandler:
    """What the transport's questions, events and frames do to the hub."""

    def __init__(self, runtime):
        self._runtime = runtime
        # The sessions the transport opened whose hello has not come yet, by
        # the transport's session id.
        self._pending: dict = {}

    async def control_opened(self) -> None:
        """A control connection is live; the transport replays its sessions.

        The live shares' table is sent on the new connection once this
        returns, since the connection's answers are read after it.
        """
        self._pending.clear()
        asyncio.get_running_loop().create_task(self._push_shares())

    async def _push_shares(self) -> None:
        try:
            await push_shares(self._runtime)
        except StreamRefusedError as error:
            LOGGER.warning("the transport did not take the live shares: %s", error.code)

    async def answer_question(self, question: str, fields: dict) -> dict:
        """Answer one of the transport's five questions.

        Args:
            question: ``peer``, ``ticket``, ``entry``, ``token`` or ``guest``.
            fields: The question's fields.

        Returns:
            The answer's fields: the admission, the binding, the target or
            the material, or ``{code, params}``.
        """
        if question == CHANNEL_QUESTION_PEER:
            return await asyncio.to_thread(self._answer_peer, fields)
        if question == CHANNEL_QUESTION_TICKET:
            return await asyncio.to_thread(self._answer_ticket, fields)
        if question == CHANNEL_QUESTION_ENTRY:
            return await self._answer_entry(fields)
        if question == CHANNEL_QUESTION_TOKEN:
            return await self._answer_token(fields)
        if question == CHANNEL_QUESTION_GUEST:
            return await guest_answer(fields)
        return _refusal(CHANNEL_CODE_CONTROL_UNAVAILABLE, {})

    async def take_event(self, event: str, fields: dict) -> None:
        """Take one event of the transport.

        Args:
            event: ``session_open``, ``session_end`` or ``stream``.
            fields: The event's fields.
        """
        if event == CHANNEL_EVENT_SESSION_OPEN:
            self._open_session(fields)
        elif event == CHANNEL_EVENT_SESSION_END:
            await self._end_session(fields)
        elif event == CHANNEL_EVENT_STREAM:
            await self._take_stream(fields)

    async def take_frame(self, session_id: str, frame: dict) -> None:
        """Take one frame of one session.

        Args:
            session_id: The transport's session id.
            frame: The frame, ``type`` included.
        """
        kind = str(frame.get("type", "") or "")
        pending = self._pending.get(session_id)
        if pending is not None:
            if kind == CHANNEL_FRAME_HELLO:
                await self._admit(pending, frame)
            elif kind == CHANNEL_FRAME_LEAVE:
                await self._leave(pending)
            else:
                await pending.refuse(CHANNEL_CODE_HELLO_INVALID, {})
                self._pending.pop(session_id, None)
            return
        session = self._live(session_id)
        if session is None:
            return
        if kind == CHANNEL_FRAME_REPORT:
            await self._take_report(session, frame)
        elif kind == CHANNEL_FRAME_LEAVE:
            await self._leave(session)
        elif kind in SESSION_VERBS and session.role == CHANNEL_ROLE_CLIENT:
            await relay_session_verb(self._runtime, session, frame)
        elif kind == CHANNEL_FRAME_REPLY and session.role == CHANNEL_ROLE_AGENT:
            self._runtime.channel_replies.resolve(session.key, frame)

    # --- questions ---

    def _answer_peer(self, fields: dict) -> dict:
        """Whose a knock's static key is, and the psk its session takes."""
        refusal = admit(_int(fields.get("protocol")))
        if refusal is not None:
            return refusal
        role = str(fields.get("role", "") or "")
        public_key = str(fields.get("public_key", "") or "")
        device = DeviceRegistry().find_by_public_key(public_key)
        if device is not None:
            found = (CHANNEL_ROLE_AGENT, device.id, device.client.token_sha256)
        else:
            client = ClientRegistry().find_by_public_key(public_key)
            if client is None:
                self._runtime.channel_port.record_failure()
                return _refusal(CHANNEL_CODE_BINDING_UNKNOWN, {})
            found = (CHANNEL_ROLE_CLIENT, client.id, client.token_sha256)
        if found[0] != role:
            return _refusal(CHANNEL_CODE_ROLE_MISMATCH, {"role": role})
        if not found[2]:
            return _refusal(CHANNEL_CODE_BINDING_UNKNOWN, {})
        return {"binding_id": found[1], "role": found[0], "psk": str(found[2])}

    def _answer_ticket(self, fields: dict) -> dict:
        """Whether a join's ticket is good, and the binding it makes.

        Admission by protocol comes first, so a refused peer has not spent
        the link. The ticket then leaves the store in one step and is
        judged. An agent lands on the row the ticket names, else on the row
        whose ``machine_id`` it reports, else on a new one; a client lands
        on the row whose ``machine_id`` it reports, else on the row its link
        was made for.
        """
        runtime = self._runtime
        try:
            request = ChannelJoin.model_validate(
                {
                    key: value
                    for key, value in fields.items()
                    if key not in ("public_key", "address", "listener")
                }
            )
        except ValidationError:
            return _refusal(CHANNEL_CODE_TICKET_SPENT, {})
        refusal = admit(request.protocol)
        if refusal is not None:
            return refusal
        paused_s = runtime.channel_port.pause_remaining_s()
        if paused_s > 0:
            return _refusal(
                CHANNEL_CODE_ADMISSION_PAUSED, {"retry_after_s": math.ceil(paused_s)}
            )
        if request.role not in ROLES:
            runtime.channel_port.record_failure()
            return _refusal(CHANNEL_CODE_ROLE_MISMATCH, {"role": request.role})
        try:
            ticket = spend_ticket(runtime.enrollments, request.ticket, request.role)
        except KeyError:
            runtime.channel_port.record_failure()
            return _refusal(CHANNEL_CODE_TICKET_SPENT, {})
        except ValueError:
            runtime.channel_port.record_failure()
            return _refusal(CHANNEL_CODE_ROLE_MISMATCH, {"role": request.role})
        public_key = str(fields.get("public_key", "") or "")
        address = unmapped(str(fields.get("address", "") or ""))
        if request.role == CHANNEL_ROLE_AGENT:
            binding_id, token = join_agent(
                runtime, request, ticket, public_key=public_key, address=address
            )
        else:
            try:
                binding_id, token = join_client(
                    runtime, request, ticket, public_key=public_key
                )
            except KeyError:
                runtime.channel_port.record_failure()
                return _refusal(CHANNEL_CODE_TICKET_SPENT, {})
        return {"binding_id": binding_id, "token": token}

    async def _answer_entry(self, fields: dict) -> dict:
        """Where a stream goes, judged for its binding now."""
        session_id = str(fields.get("session", "") or "")
        open_body = fields.get("open")
        share_id = self._runtime.web_share_guests.share_of(session_id)
        if share_id:
            if not isinstance(open_body, dict):
                return _refusal(CHANNEL_CODE_BINDING_UNKNOWN, {})
            return await guest_entry_answer(self._runtime, share_id, open_body)
        session = self._live(session_id)
        binding_id = str(fields.get("binding_id", "") or "")
        if session is None or not isinstance(open_body, dict):
            return _refusal(CHANNEL_CODE_BINDING_UNKNOWN, {})
        return await entry_answer(
            self._runtime,
            role=session.role,
            binding_id=binding_id or session.key,
            open_body=open_body,
        )

    async def _answer_token(self, fields: dict) -> dict:
        """The material a client's or a visitor's ``service`` frame is handed."""
        session_id = str(fields.get("session", "") or "")
        frame = fields.get("frame")
        frame = frame if isinstance(frame, dict) else {}
        share_id = self._runtime.web_share_guests.share_of(session_id)
        if share_id:
            return await guest_token_answer(self._runtime, share_id, frame)
        session = self._live(session_id)
        if session is None or session.role != CHANNEL_ROLE_CLIENT:
            return _refusal(CHANNEL_CODE_BINDING_UNKNOWN, {})
        if frame.get("is_panel") is True:
            code, params = await asyncio.to_thread(
                panel_material, self._runtime, session.key
            )
        else:
            entry_id = str(frame.get("id", "") or "")
            code, params = await asyncio.to_thread(
                service_material, self._runtime, session.key, entry_id
            )
        if code:
            return _refusal(code, params)
        return {"params": params}

    # --- events ---

    def _open_session(self, fields: dict) -> None:
        """A handshake completed for an admitted key; its hello follows."""
        session_id = str(fields.get("session", "") or "")
        role = str(fields.get("role", "") or "")
        self._pending[session_id] = ChannelSession(
            key=str(fields.get("binding_id", "") or ""),
            role=role,
            session_id=session_id,
            channel=self._runtime.channel,
            loop=asyncio.get_running_loop(),
            address=unmapped(str(fields.get("address", "") or "")),
            listener=str(fields.get("listener", "") or ""),
        )
        self._pending[session_id].local_address = unmapped(
            str(fields.get("local_address", "") or "")
        )

    async def _end_session(self, fields: dict) -> None:
        """The transport ended a session; the binding may be offline now."""
        session_id = str(fields.get("session", "") or "")
        pending = self._pending.pop(session_id, None)
        if pending is not None:
            pending.mark_ended()
            return
        if self._runtime.web_share_guests.end(session_id):
            self._runtime.events.publish(WEB_EVENT_CLIENTS)
            return
        session = self._live(session_id)
        if session is None:
            return
        runtime = self._runtime
        if session.role == CHANNEL_ROLE_AGENT:
            if runtime.agent_sessions.detach(session):
                device = await asyncio.to_thread(DeviceRegistry().get, session.key)
                if device is not None:
                    await asyncio.to_thread(record_offline, runtime, device)
        else:
            runtime.client_sessions.detach(session)
            runtime.events.publish(WEB_EVENT_CLIENTS)

    async def _take_stream(self, fields: dict) -> None:
        """An agent opened ``log`` or ``package``: take it and serve it."""
        session = self._live(str(fields.get("session", "") or ""))
        open_body = fields.get("open")
        if session is None or not isinstance(open_body, dict):
            return
        kind = str(open_body.get("kind", "") or "")
        if session.role != CHANNEL_ROLE_AGENT or kind not in (
            CHANNEL_STREAM_LOG,
            CHANNEL_STREAM_PACKAGE,
        ):
            return
        try:
            stream = await self._runtime.channel.attach_stream(
                fields.get("stream"), open_body, peer_key=session.key
            )
            await stream.accept()
        except AgentOfflineError:
            return
        if kind == CHANNEL_STREAM_PACKAGE:
            asyncio.get_running_loop().create_task(
                serve_package_stream(self._runtime, session, stream)
            )
        else:
            asyncio.get_running_loop().create_task(
                serve_log_stream(self._runtime, session, stream)
            )

    # --- frames ---

    async def _admit(self, session: ChannelSession, frame: dict) -> None:
        """Judge a pending session's hello: welcome, or a refusal."""
        runtime = self._runtime
        try:
            hello = ChannelHello.model_validate(frame)
        except ValidationError:
            await self._refuse_pending(session, CHANNEL_CODE_HELLO_INVALID)
            return
        if hello.id != session.key or hello.role != session.role:
            await self._refuse_pending(session, CHANNEL_CODE_HELLO_INVALID)
            return
        refusal = admit(hello.protocol)
        if refusal is not None:
            await self._refuse_pending(session, refusal["code"], refusal["params"])
            return
        session.name = hello.name
        session.software = hello.software
        self._pending.pop(session.session_id, None)
        if session.role == CHANNEL_ROLE_GUEST:
            await self._admit_guest(session)
            return
        if session.role == CHANNEL_ROLE_AGENT:
            device = await asyncio.to_thread(DeviceRegistry().get, session.key)
            if device is None:
                await session.refuse(CHANNEL_CODE_BINDING_UNKNOWN, {})
                return
            runtime.agent_sessions.attach(session)
            await session.send_json(await asyncio.to_thread(welcome_frame))
            await asyncio.to_thread(
                record_hello,
                runtime,
                device,
                name=session.name,
                peer_host=session.address,
                reached_host=getattr(session, "local_address", ""),
            )
            await asyncio.to_thread(
                DeviceRegistry().note_agent_version, device.id, session.version
            )
            await asyncio.to_thread(runtime.settle_legacy_channel)
            return
        client = await asyncio.to_thread(ClientRegistry().get, session.key)
        if client is None:
            await session.refuse(CHANNEL_CODE_BINDING_UNKNOWN, {})
            return
        runtime.client_sessions.attach(session)
        await asyncio.to_thread(
            channel_state.note_client_scope,
            runtime,
            client.id,
            peer_host=session.address,
            reached_host=getattr(session, "local_address", ""),
            listener_port=FRP_LOOPBACK_PORTS.get(session.listener, 0),
        )
        await session.send_json(await asyncio.to_thread(welcome_frame))
        await asyncio.to_thread(
            ClientRegistry().record_seen,
            client.id,
            hostname="",
            platform={},
            version=session.version,
        )
        runtime.events.publish(WEB_EVENT_CLIENTS)

    async def _admit_guest(self, session: ChannelSession) -> None:
        """Welcome a visitor's session while its share is live; it gets no state."""
        runtime = self._runtime
        if not await asyncio.to_thread(is_share_live, session.key):
            await session.refuse(WEB_SHARE_CODE_SHARE_UNKNOWN, {})
            return
        runtime.web_share_guests.add(session.key, session)
        session.is_admitted = True
        await session.send_json(await asyncio.to_thread(welcome_frame))
        runtime.events.publish(WEB_EVENT_CLIENTS)

    async def _refuse_pending(
        self, session: ChannelSession, code: str, params: "dict | None" = None
    ) -> None:
        self._pending.pop(session.session_id, None)
        await session.refuse(code, params)

    async def _take_report(self, session: ChannelSession, frame: dict) -> None:
        if session.role == CHANNEL_ROLE_AGENT:
            device = await asyncio.to_thread(DeviceRegistry().get, session.key)
            if device is None:
                return
            await _AgentFrames(
                self._runtime, session, device, hub_version=HUB_VERSION
            ).take_report(frame)
            return
        client = await asyncio.to_thread(ClientRegistry().get, session.key)
        if client is None:
            return
        await _ClientFrames(self._runtime, session, client).take_report(frame)

    async def _leave(self, session: ChannelSession) -> None:
        """Take a peer's word that it is going, and end its binding."""
        runtime = self._runtime
        self._pending.pop(session.session_id, None)
        if session.role == CHANNEL_ROLE_AGENT:
            await asyncio.to_thread(DeviceRegistry().drop_token, session.key)
            try:
                await session.send_json({"type": CHANNEL_FRAME_LEFT}, is_last=True)
            except AgentOfflineError:
                pass
            await asyncio.to_thread(runtime.forget_device, session.key)
            return
        registry = ClientRegistry()
        client = await asyncio.to_thread(registry.get, session.key)
        if client is not None:
            await asyncio.to_thread(revoke_client_key, registry, client)
        await asyncio.to_thread(registry.forget, session.key)
        try:
            await session.send_json({"type": CHANNEL_FRAME_LEFT}, is_last=True)
        except AgentOfflineError:
            pass
        await asyncio.to_thread(runtime.forget_client, session.key)
        await asyncio.to_thread(
            end_client_panel_sessions,
            runtime,
            why=SESSION_END_LEFT,
            names={session.key: client.name} if client is not None else None,
        )
        runtime.events.publish(WEB_EVENT_CLIENTS)

    def _live(self, session_id: str) -> "ChannelSession | None":
        """The admitted session the transport names, or None."""
        found = self._runtime.agent_sessions.by_session_id(session_id)
        if found is None:
            found = self._runtime.client_sessions.by_session_id(session_id)
        return found


def welcome_frame() -> dict:
    """The hub's identity card, with the hub's clock an agent checks tokens by."""
    return {
        "type": CHANNEL_FRAME_WELCOME,
        "protocol": PROTOCOL,
        "role": CHANNEL_ROLE_HUB,
        "id": hub_id(),
        "name": hub_name(),
        "software": f"neutrino_hub/{HUB_VERSION}",
        "time": time.time(),
    }


def join_agent(
    runtime, request: ChannelJoin, ticket: dict, *, public_key: str, address: str
) -> tuple:
    """Bind a machine to its row, or a new one, and issue its token.

    Args:
        runtime: The shared runtime.
        request: The join as the ticket question carried it.
        ticket: The spent ticket.
        public_key: The agent's static public key.
        address: Where the join came from.

    Returns:
        ``(binding_id, token)``.
    """
    registry = DeviceRegistry()
    device = None
    if ticket.get("device_id"):
        device = registry.get(ticket["device_id"])
    if device is None:
        device = registry.find_by_machine_id(request.machine_id)
    name = ticket.get("name") or (device.name if device else None) or request.name
    if device is None:
        device = registry.create(name, machine_id=request.machine_id)
    else:
        device = registry.annotate(device.id, {"name": name or device.name})
        registry.note_machine(device.id, machine_id=request.machine_id)
    key = device.id
    token = registry.issue_token(key)
    registry.set_public_key(key, public_key)
    if request.platform:
        runtime.device_platform[key] = dict(request.platform)
        registry.note_platform(key, dict(request.platform))
    if request.name:
        runtime.device_hostname[key] = request.name
    if address:
        runtime.device_address[key] = address
    runtime.events.publish(WEB_EVENT_DEVICES)
    return key, token


def join_client(runtime, request: ChannelJoin, ticket: dict, *, public_key: str):
    """Bind a person's program to the row it had, else to its link's row.

    A machine that already has a row lands back on it: the link's waiting
    row goes, the old row takes the link's name and permission and keeps
    its key, its switch and everything it last reported.

    Args:
        runtime: The shared runtime.
        request: The join as the ticket question carried it.
        ticket: The spent ticket.
        public_key: The client's static public key.

    Returns:
        ``(binding_id, token)``.

    Raises:
        KeyError: When the ticket names a row that is gone.
    """
    registry = ClientRegistry()
    client_id = str(ticket.get("client_id", ""))
    waiting = registry.get(client_id)
    if waiting is None:
        raise KeyError(client_id)
    enrolled = registry.find_by_machine_id(request.machine_id)
    if enrolled is not None and enrolled.id != client_id:
        registry.forget(client_id)
        runtime.forget_client(client_id)
        client_id = enrolled.id
        registry.rename(client_id, str(ticket.get("name") or "") or enrolled.name)
        registry.set_permission(
            client_id,
            waiting.permission,
            waiting.permission_devices,
            waiting.permission_entries,
        )
    registry.record_seen(
        client_id,
        hostname=request.name,
        platform=request.platform,
        version=version_of_software(request.software),
        machine_id=request.machine_id,
    )
    token = registry.issue_token(client_id)
    registry.set_public_key(client_id, public_key)
    runtime.events.publish(WEB_EVENT_CLIENTS)
    return client_id, token


async def serve_package_stream(runtime, session, stream) -> None:
    """Serve a ``package`` stream an agent opened: the bytes, then their digest.

    ``{module, artifact, digest}`` names one artifact of a module, or of a
    program the agent runs itself such as cc-switch, from the hub's cache by
    its digest; ``{}`` is the agent's own package for its platform. The
    bytes go down as ``data`` records and the close carries their ``sha256``
    and the file's own ``name``, as its sources or its release name it, with
    no directory. A module's fetch and its bytes are counted into its task as
    ``hub: fetching`` and ``hub: sending <title>, <sent> / <total> MB to
    <device>`` lines while they go.

    Args:
        runtime: The shared runtime.
        session: The agent's session, on the transport or the legacy listener.
        stream: The stream, closed here.
    """
    module = str(stream.args.get("module", "") or "")
    artifact = str(stream.args.get("artifact", "") or "")
    digest = str(stream.args.get("digest", "") or "")
    platform = dict(runtime.device_platform.get(session.key, {}))
    if not platform:
        platform = await _platform_once_reported(runtime, session.key)
    is_module = bool(module) and module in load_module_manifests()
    on_progress = None
    if is_module:
        on_progress = functools.partial(
            _publish_module_line_from_thread,
            asyncio.get_running_loop(),
            runtime,
            module_task_label(session.key, module),
        )
    try:
        path, title, name = await asyncio.to_thread(
            _package_file, runtime, module, platform, on_progress, artifact, digest
        )
    except AgentArtifactFetchError as error:
        if not module and not platform:
            session.is_reinstall_due = True
        if is_module:
            for line in _refusal_lines(error.code, error.params):
                publish_module_line(
                    runtime, module_task_label(session.key, module), line
                )
        LOGGER.warning(
            "package stream for %s refused: %s %s",
            module or "agent",
            error.code,
            error.params,
        )
        await stream.close(error.code, error.params)
        return
    progress = None
    size = 0
    if is_module:
        progress = AgentModuleSendProgress(
            title=title,
            recipient=session.name,
            on_line=functools.partial(
                publish_module_line, runtime, module_task_label(session.key, module)
            ),
        )
        size = await asyncio.to_thread(_file_size, path)
    sent = 0
    sent_digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            while True:
                chunk = await asyncio.to_thread(handle.read, CHANNEL_CHUNK_BYTES)
                if not chunk:
                    break
                sent_digest.update(chunk)
                await stream.send_bytes(chunk)
                sent += len(chunk)
                if progress is not None:
                    progress.note(sent, size)
    except OSError:
        await stream.close("module_artifact_missing", {})
        return
    except AgentOfflineError:
        return
    if progress is not None:
        progress.note(sent, size, is_done=True)
    await stream.close("", {"sha256": sent_digest.hexdigest(), "name": name})


async def serve_log_stream(runtime, session, stream) -> None:
    """Serve a ``log`` stream an agent opened: its lines become one task.

    ``{module}`` names the module being installed or uninstalled. The task
    runs under :data:`WEB_TASK_LABEL_MODULE`, which is how the module list
    finds it for the panel to follow on ``/ws/hub/task``, and it ends with
    the close: the module's ``state``, and the code when the operation
    failed.

    Args:
        runtime: The shared runtime.
        session: The agent's session.
        stream: The stream, closed by the agent.
    """
    module = str(stream.args.get("module", "") or "")
    runtime.tasks.start(
        label=module_task_label(session.key, module), source=_log_lines(stream)
    )
    await stream.wait_closed()


def module_task_label(device_id: str, module: str) -> str:
    """The label a module's install or uninstall task runs under."""
    return WEB_TASK_LABEL_MODULE.format(device_id=device_id, module=module)


def publish_module_line(runtime, label: str, line: str) -> None:
    """Add one ``hub:`` line to a module's running task, or log it.

    Args:
        runtime: The shared runtime.
        label: The task's label, from :func:`module_task_label`.
        line: The line, without its newline.
    """
    task = runtime.tasks.running(label)
    if task is None:
        LOGGER.info("%s", line)
        return
    task.publish(line + "\n")


async def _log_lines(stream):
    """A log stream's lines as they arrive, then what it closed with.

    Yields:
        Each line, then a JSON line ``{"code", "params"}`` when the close
        carries a code, then ``[<state>]`` for the module's state after
        the operation.

    Raises:
        TaskExitStatusError: When the close carries a code; the task ends
            with the ``exit_code`` its params name, else 1.
    """
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    while True:
        item = await stream.recv()
        if item is None:
            break
        if item[0] != "data":
            continue
        text = decoder.decode(item[1])
        if text:
            yield text
    info = stream.close_info or {}
    params = dict(info.get("params") or {})
    state = str(params.pop("state", "") or "")
    if info.get("code"):
        yield json.dumps({"code": info["code"], "params": params}) + "\n"
    if state:
        yield f"[{state}]\n"
    if info.get("code"):
        raise TaskExitStatusError(_failed_exit_code(params))


def _failed_exit_code(params: dict) -> int:
    """The exit status a failed operation's params name, 1 when they name
    none other than 0."""
    try:
        return int(params.get("exit_code", 1)) or 1
    except (TypeError, ValueError):
        return 1


def _publish_module_line_from_thread(loop, runtime, label: str, line: str) -> None:
    """Hand one task line from a worker thread to the event loop."""
    loop.call_soon_threadsafe(publish_module_line, runtime, label, line)


def _file_size(path) -> int:
    """A file's size in bytes, 0 when it cannot be read."""
    try:
        return path.stat().st_size
    except OSError:
        return 0


async def _platform_once_reported(runtime, key: str) -> dict:
    """The device's platform once its first report of the connection lands.

    An agent asks for its own package right after the welcome, before its
    first report; the platform that report carries is what names the package.

    Args:
        runtime: The shared runtime.
        key: The device's id.

    Returns:
        The platform tuple, or an empty dict when none arrived in
        ``CHANNEL_PACKAGE_PLATFORM_WAIT_S``.
    """
    deadline = time.monotonic() + CHANNEL_PACKAGE_PLATFORM_WAIT_S
    while time.monotonic() < deadline:
        platform = dict(runtime.device_platform.get(key, {}))
        if platform:
            return platform
        await asyncio.sleep(CHANNEL_PACKAGE_PLATFORM_POLL_S)
    return {}


def _refusal_lines(code: str, params: dict) -> list:
    """The module output lines a refused ``package`` stream writes.

    Args:
        code: The refusal's code.
        params: Its params.

    Returns:
        For ``download_failed``, one line naming the file and one per source
        with its reason and detail; for any other code, one line with the
        code and its params.
    """
    if code != DownloadFailedError.code:
        detail = " ".join(f"{key}={value}" for key, value in sorted(params.items()))
        return [f"hub: the download failed: {code} {detail}".rstrip()]
    lines = [f"hub: no source served {params.get('file', '')}"]
    for item in params.get("sources") or []:
        said = f"hub:   {item.get('source', '')}: {item.get('reason', '')}"
        if item.get("detail"):
            said += f" ({item['detail']})"
        lines.append(said)
    return lines


def _package_file(
    runtime,
    module: str,
    platform: dict,
    on_progress=None,
    artifact: str = "",
    digest: str = "",
) -> tuple:
    """Where the package a ``package`` stream asks for is on this hub.

    Returns:
        ``(path, title, name)``: the file, what progress lines call it,
        empty for the agent's own package, and the name the close gives it.

    Raises:
        AgentArtifactFetchError: The caches' own typed reasons.
    """
    if not module:
        path = runtime.agent_packages.package(
            family=platform_family(platform), architecture=str(platform.get("arch", ""))
        )
        return path, "", path.name
    held = runtime.agent_modules.artifact(
        module=module,
        artifact=artifact,
        digest=digest,
        platform=platform,
        on_progress=on_progress,
    )
    return held.path, held.title, held.file


def _sessions_of(report: dict) -> list:
    """The shell sessions a report's ``machine`` section lists."""
    machine = report.get("machine") if isinstance(report, dict) else None
    sessions = machine.get("sessions") if isinstance(machine, dict) else None
    return sessions if isinstance(sessions, list) else []


def _is_panel_change(previous: dict, report: dict) -> bool:
    """Whether a report says anything new about what the panel draws."""
    return any(
        previous.get(section) != report.get(section)
        for section in REPORT_PANEL_SECTIONS
    )


def _int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _refusal(code: str, params: dict) -> dict:
    return {"code": code, "params": dict(params or {})}


class _AgentFrames:
    """What an agent's reports do to the hub."""

    def __init__(self, runtime, session: ChannelSession, device, *, hub_version: str):
        self._runtime = runtime
        self._session = session
        self._device = device
        self._hub_version = hub_version

    async def take_report(self, report: dict) -> None:
        """Record one report, tell the panel, offer the state once, and send
        ``reinstall`` once to an older agent refused its package for want of
        the platform this report names, unless it is on the hub's machine."""
        runtime = self._runtime
        session = self._session
        key = self._device.id
        is_first = not session.report
        is_panel_change = _is_panel_change(session.report, report)
        is_module_change = session.report.get("modules") != report.get("modules")
        is_session_change = _sessions_of(session.report) != _sessions_of(report)
        session.record_report(report)
        await asyncio.to_thread(
            record_report,
            runtime,
            self._device,
            report,
            peer_host=session.address,
            is_first=is_first,
        )
        session.note_report_recorded()
        if is_module_change:
            runtime.published_services.schedule_refresh()
        if is_panel_change or is_session_change:
            runtime.events.publish(WEB_EVENT_DEVICE_REPORT, key)
        if is_session_change:
            await asyncio.to_thread(
                channel_state.push_states, runtime, CHANNEL_ROLE_CLIENT
            )
        runtime.events.publish(
            WEB_EVENT_METRICS, key, data=dict(runtime.device_metrics.get(key, {}))
        )
        if session.offered_hash is None:
            document = await asyncio.to_thread(channel_state.agent_state, runtime, key)
            if document["hash"] != session.state_hash:
                await session.push_state(document)
            session.offered_hash = document["hash"]
        elif await asyncio.to_thread(runtime.desired_states.uses_gateway_models, key):
            # Whether the gateway serves moves with no write to announce it,
            # so a machine whose AI tools, SiYuan accounts or Ayakaleaf use
            # it has its state read again.
            document = await asyncio.to_thread(channel_state.agent_state, runtime, key)
            if document["hash"] != session.offered_hash:
                await session.push_state(document)
                session.offered_hash = document["hash"]
        if getattr(session, "is_reinstall_due", False) and runtime.device_platform.get(
            key
        ):
            session.is_reinstall_due = False
            if not _is_older_release(session.version, self._hub_version):
                return
            if await asyncio.to_thread(_is_hub_machine, self._device):
                LOGGER.info(
                    "agent %s on %s is on the hub's own machine; "
                    "the hub's update installs it",
                    session.name,
                    session.version,
                )
                return
            await _send_reinstall(session, self._hub_version)


def _is_hub_machine(device) -> bool:
    """Whether a device is the machine this hub runs on, by the id its join noted."""
    own_machine = machine_id()
    return bool(own_machine) and device.machine_id == own_machine


def _is_older_release(version: str, than: str) -> bool:
    """Whether one released version comes before another.

    Returns:
        True when ``version`` orders before ``than``; False when either does
        not parse or ends in ``CHANNEL_DEV_VERSION_SUFFIX``.
    """
    if version.endswith(CHANNEL_DEV_VERSION_SUFFIX) or than.endswith(
        CHANNEL_DEV_VERSION_SUFFIX
    ):
        return False
    older = parse_version(version)
    newer = parse_version(than)
    return older is not None and newer is not None and older < newer


async def _send_reinstall(session: ChannelSession, hub_version: str) -> None:
    """Open ``command {module: agent, verb: reinstall}`` on an agent's session.

    The agent takes its package down a ``package`` stream and installs it,
    as the machine page's Update agent has it do; the command's close is
    logged when it comes.

    Args:
        session: The agent's session.
        hub_version: The version the hub runs.
    """
    try:
        stream = await session.open_stream(
            CHANNEL_STREAM_COMMAND,
            {"module": CHANNEL_COMMAND_MODULE_AGENT, "verb": CHANNEL_VERB_REINSTALL},
        )
    except AgentOfflineError:
        return
    LOGGER.info(
        "agent %s on %s asked for its package before the hub knew its platform; "
        "reinstall sent to reach %s",
        session.name,
        session.version,
        hub_version,
    )
    asyncio.create_task(_log_reinstall_close(session.name, stream))


async def _log_reinstall_close(name: str, stream) -> None:
    """Read a ``reinstall`` command to its close and log the close."""
    while await stream.recv() is not None:
        pass
    info = stream.close_info or {"code": AgentOfflineError.code, "params": {}}
    params = {
        field: value
        for field, value in (info.get("params") or {}).items()
        if field != "output"
    }
    LOGGER.info(
        "reinstall of agent %s closed: %s %s", name, info.get("code") or "ok", params
    )


class _ClientFrames:
    """What a client's reports do to the hub."""

    def __init__(self, runtime, session: ChannelSession, client):
        self._runtime = runtime
        self._session = session
        self._client = client

    async def take_report(self, report: dict) -> None:
        """Record one report and hand the state down when the hashes differ,
        or whatever they are when the report says ``is_refresh``."""
        runtime = self._runtime
        session = self._session
        session.record_report(report)
        machine = report.get("machine")
        machine = machine if isinstance(machine, dict) else {}
        await asyncio.to_thread(
            ClientRegistry().record_seen,
            self._client.id,
            hostname=str(machine.get("hostname", "") or ""),
            platform=(
                dict(machine["platform"])
                if isinstance(machine.get("platform"), dict)
                else {}
            ),
            version="",
            os_machine_id=str(machine.get("os_machine_id", "") or ""),
        )
        session.note_report_recorded()
        document = await asyncio.to_thread(
            channel_state.client_state, runtime, self._client.id
        )
        if report.get("is_refresh") is True or document["hash"] != session.state_hash:
            await session.push_state(document)
        session.offered_hash = document["hash"]


__all__ = [
    "ChannelControlHandler",
    "StreamRefusedError",
    "join_agent",
    "join_client",
    "module_task_label",
    "publish_module_line",
    "serve_log_stream",
    "serve_package_stream",
    "welcome_frame",
]

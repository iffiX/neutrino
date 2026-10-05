"""The agent channel's port rides the panel's settings file, and both
listeners believe only the socket.

One field beside ``listen_port``: the example carries it, a written value is
read back, and a settings file from before the field existed falls back to
the default rather than failing to serve. The agent port and the panel are
served here by real uvicorn servers built from the configurations the hub
runs: forwarded-address headers from loopback leave the peer at loopback
and the scheme the socket's own,
and a WebSocket message past the agent port's cap closes the socket before
the application reads it.
"""

import asyncio
import http.client
import json
import ssl

import uvicorn
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from neutrino_hub.cli import run
from neutrino_hub.modules.channel.constants import CHANNEL_MESSAGE_BYTES_MAX
from neutrino_hub.modules.channel.port_guard import ChannelPortGuard
from tests.conftest import self_signed_pair
from neutrino_hub.utils.constants import UTILS_EXAMPLES_DIR
from neutrino_hub.web.constants import WEB_DEFAULT_AGENT_LISTEN_PORT


def settings_file(tmp_path, monkeypatch, content: dict):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    path = tmp_path / "web" / "settings.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(content), encoding="utf-8")


def test_a_written_port_is_read_back(tmp_path, monkeypatch):
    settings_file(tmp_path, monkeypatch, {"agent_listen_port": 9443})

    assert run._configured_agent_port() == 9443


def test_a_settings_file_without_the_field_gets_the_default(tmp_path, monkeypatch):
    settings_file(tmp_path, monkeypatch, {"listen_port": 8080})

    assert run._configured_agent_port() == WEB_DEFAULT_AGENT_LISTEN_PORT


def test_the_example_carries_the_field():
    example = json.loads(
        (UTILS_EXAMPLES_DIR / "web" / "settings.example.json").read_text(
            encoding="utf-8"
        )
    )

    assert example["agent_listen_port"] == WEB_DEFAULT_AGENT_LISTEN_PORT


def recording_app(received: list) -> FastAPI:
    """Answers where a request came from, and echoes each socket message."""
    app = FastAPI()

    @app.get("/peer")
    async def peer(request: Request):
        return {"host": request.client.host, "scheme": request.url.scheme}

    @app.websocket("/echo")
    async def echo(websocket: WebSocket):
        await websocket.accept()
        try:
            while True:
                message = await websocket.receive_bytes()
                received.append(len(message))
                await websocket.send_bytes(message[:16])
        except WebSocketDisconnect:
            return

    return app


def client_context() -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


async def started(config: uvicorn.Config, app: FastAPI):
    """A real server on the configuration with the application swapped in."""
    config.app = app
    config.factory = False
    config.port = 0
    config.log_level = "warning"
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    return server, task, port


def peer_seen(port: int, *, context=None) -> str:
    connection = (
        http.client.HTTPSConnection("127.0.0.1", port, context=context, timeout=5)
        if context
        else http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    )
    connection.request(
        "GET",
        "/peer",
        headers={"X-Forwarded-For": "203.0.113.9", "X-Forwarded-Proto": "https"},
    )
    seen = json.loads(connection.getresponse().read())
    connection.close()
    return f"{seen['scheme']}://{seen['host']}"


def agent_config(tmp_path, monkeypatch) -> uvicorn.Config:
    certificate, key, _ = self_signed_pair(tmp_path)
    monkeypatch.setattr(run, "WEB_AGENT_TLS_CERT_PATH", certificate)
    monkeypatch.setattr(run, "_agent_port_guard", ChannelPortGuard)
    monkeypatch.setattr(run, "_configured_agent_port", lambda: 0)
    return run._agent_config("127.0.0.1", key)


def test_the_agent_port_believes_the_socket_and_not_a_forwarded_header(
    tmp_path, monkeypatch
):
    config = agent_config(tmp_path, monkeypatch)

    async def scenario():
        server, task, port = await started(config, recording_app([]))
        host = await asyncio.to_thread(peer_seen, port, context=client_context())
        server.should_exit = True
        await task
        return host

    assert config.proxy_headers is False
    assert asyncio.run(scenario()) == "https://127.0.0.1"


def test_the_panel_believes_the_socket_and_not_a_forwarded_header(monkeypatch):
    config = run._panel_config("127.0.0.1", 0)

    async def scenario():
        server, task, port = await started(config, recording_app([]))
        host = await asyncio.to_thread(peer_seen, port)
        server.should_exit = True
        await task
        return host

    assert config.proxy_headers is False
    assert asyncio.run(scenario()) == "http://127.0.0.1"


def test_a_message_past_the_cap_closes_the_socket_unread(tmp_path, monkeypatch):
    config = agent_config(tmp_path, monkeypatch)
    received: list = []

    async def scenario():
        server, task, port = await started(config, recording_app(received))
        uri = f"wss://127.0.0.1:{port}/echo"
        async with connect(uri, ssl=client_context(), max_size=None) as socket:
            await socket.send(b"x" * CHANNEL_MESSAGE_BYTES_MAX)
            echoed = await asyncio.wait_for(socket.recv(), 5)
            await socket.send(b"x" * (CHANNEL_MESSAGE_BYTES_MAX + 1))
            try:
                await asyncio.wait_for(socket.recv(), 5)
                close_code = None
            except ConnectionClosed as closed:
                close_code = closed.rcvd.code if closed.rcvd else None
        server.should_exit = True
        await task
        return echoed, close_code

    echoed, close_code = asyncio.run(scenario())

    assert config.ws_max_size == CHANNEL_MESSAGE_BYTES_MAX
    assert echoed == b"x" * 16
    assert close_code == 1009
    assert received == [CHANNEL_MESSAGE_BYTES_MAX]

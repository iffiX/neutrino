"""A client runs one command on a managed machine through an ``exec`` stream.

The Clients page makes a link; the check joins with it over the pinned agent
port as a client, is given ``exec`` alone, and opens ``exec`` on the hub's
own agent, else on the first online machine the panel lists. The command
writes ``out`` to stdout and ``err`` to stderr and exits 7: each arrives on
its own ``fd`` and the close carries ``exit_code`` 7. Then ``cat`` is sent
``hello`` and the input-ended frame: ``hello`` comes back and the close
carries 0. On a Windows machine both run through ``cmd /c``. The client
leaves at the end, which deletes its row.

Run on a set-up box with at least one exposed address, so a link has an
address to carry, and one machine whose agent is online.
"""

import contextlib
import json
import time

import pytest

connect_probe = pytest.importorskip(
    "connect_probe", reason="needs the agent package for the client's socket"
)

STDIO_ARGV = ["sh", "-c", "echo out; echo err >&2; exit 7"]
STDIO_ARGV_WINDOWS = ["cmd", "/c", "echo out& echo err 1>&2& exit /b 7"]
CAT_ARGV = ["cat"]
CAT_ARGV_WINDOWS = ["cmd", "/c", "more"]
STDOUT_FD = 1
STDERR_FD = 2
CREDIT_BYTES = 1024 * 1024
EXEC_TIMEOUT_S = 30.0


@pytest.fixture
def exec_client(panel):
    """A client allowed ``exec`` alone, its socket open, and its row gone after."""
    status, made = panel.call(
        "POST", "/hub/client/enrollment/create", {"name": "integration-exec"}
    )
    if status == 400 and made.get("detail", {}).get("code") == "no_reachable_address":
        pytest.skip("this box exposes no address a client could be sent to")
    assert status == 200, made
    urls, ticket, fingerprint = connect_probe.parse_client_link(made["link"])
    gateway_url, client_id, token = connect_probe.join(urls, ticket, fingerprint)
    channel = connect_probe.Channel(gateway_url, fingerprint)
    try:
        status, answer = panel.call(
            "POST",
            "/hub/client/permission/set",
            {"client_id": client_id, "kinds": ["exec"]},
        )
        assert status == 200, answer
        channel.open(client_id, token)
        yield channel
    finally:
        channel.close()
        with contextlib.suppress(
            connect_probe.GatewayUnreachable, connect_probe.GatewayUntrusted
        ):
            connect_probe.BindingHttpClient(
                gateway_url=gateway_url, fingerprint=fingerprint
            ).leave(client_id, token)
        for row in panel.read("/hub/client")["clients"]:
            if row["id"] == client_id:
                panel.call("POST", "/hub/client/remove", {"client_id": client_id})


@pytest.fixture
def machine(panel) -> dict:
    """The hub's own online agent, else the first online machine listed."""
    devices = panel.read("/hub/device/online")["devices"]
    if not devices:
        pytest.skip("no machine has its agent online")
    return next((device for device in devices if device["is_hub"]), devices[0])


def is_windows(device: dict) -> bool:
    return str((device.get("platform") or {}).get("os", "")).lower() == "windows"


def run_exec(channel, stream_id: int, device_id: str, argv: list, stdin: bytes):
    """Open one ``exec``, send the stdin and ``eof``, and read to the close.

    Returns:
        The bytes by ``fd``, and the close's ``{code, params}``.
    """
    channel.send(
        {
            "type": "open",
            "stream": stream_id,
            "kind": "exec",
            "device_id": device_id,
            "argv": argv,
            "is_tty": False,
            "cols": 80,
            "rows": 24,
        }
    )
    channel.send({"type": "credit", "stream": stream_id, "bytes": CREDIT_BYTES})
    is_input_sent = False
    received: dict = {}
    deadline = time.monotonic() + EXEC_TIMEOUT_S
    while time.monotonic() < deadline:
        item = channel.next(deadline - time.monotonic())
        if item is None:
            break
        kind, payload = item
        if kind == "gone":
            return received, {"code": "socket_closed", "params": {}}
        if kind == "binary" and int.from_bytes(payload[:4], "big") == stream_id:
            frame = payload[4:]
            channel.send({"type": "credit", "stream": stream_id, "bytes": len(frame)})
            if frame:
                received[frame[0]] = received.get(frame[0], b"") + frame[1:]
            continue
        if kind != "text" or payload.get("stream") != stream_id:
            continue
        if payload.get("type") == "credit" and not is_input_sent:
            if stdin:
                channel.client.send_bytes(stream_id.to_bytes(4, "big") + stdin)
            channel.send({"type": "eof", "stream": stream_id})
            is_input_sent = True
        elif payload.get("type") == "close":
            return received, {
                "code": str(payload.get("code", "") or ""),
                "params": payload.get("params") or {},
            }
    raise AssertionError(f"no close within {EXEC_TIMEOUT_S} s: {received}")


def test_stdout_and_stderr_arrive_apart_and_the_exit_code_comes_back(
    exec_client, machine
):
    argv = STDIO_ARGV_WINDOWS if is_windows(machine) else STDIO_ARGV

    received, close = run_exec(exec_client, 1, machine["device_id"], argv, b"")

    assert close == {"code": "", "params": {"exit_code": 7}}, json.dumps(close)
    assert set(received) <= {STDOUT_FD, STDERR_FD}
    assert received.get(STDOUT_FD, b"").strip() == b"out"
    assert received.get(STDERR_FD, b"").strip() == b"err"


def test_stdin_reaches_the_command_and_the_input_ended_frame_ends_it(
    exec_client, machine
):
    argv = CAT_ARGV_WINDOWS if is_windows(machine) else CAT_ARGV

    received, close = run_exec(exec_client, 1, machine["device_id"], argv, b"hello")

    assert close == {"code": "", "params": {"exit_code": 0}}, json.dumps(close)
    assert received.get(STDOUT_FD, b"").rstrip(b"\r\n") == b"hello"
    assert received.get(STDERR_FD, b"") == b""

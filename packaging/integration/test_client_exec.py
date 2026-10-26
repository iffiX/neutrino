"""A client runs one command on a managed machine through an ``exec`` stream.

The Clients page makes a link; the check joins with it through a transport
of its own as a client, is given ``terminal`` alone, and opens ``exec`` on
the hub's own agent, else on the first online machine the panel lists. The
command writes ``out`` to stdout and ``err`` to stderr and exits 7: each
arrives in its own records and the close carries ``exit_code`` 7. Then
``cat`` is sent ``hello`` and the ``eof`` record: ``hello`` comes back and
the close carries 0. On a Windows machine both run through ``cmd /c``. The
client leaves at the end, which deletes its row.

Run on a set-up box with at least one exposed address, so a link has an
address to carry, and one machine whose agent is online.
"""

import json

import pytest

connect_probe = pytest.importorskip(
    "connect_probe", reason="needs the agent package for the client's transport"
)

STDIO_ARGV = ["sh", "-c", "echo out; echo err >&2; exit 7"]
STDIO_ARGV_WINDOWS = ["cmd", "/c", "echo out& echo err 1>&2& exit /b 7"]
CAT_ARGV = ["cat"]
CAT_ARGV_WINDOWS = ["cmd", "/c", "more"]
EXEC_TIMEOUT_S = 30.0


@pytest.fixture
def exec_client(panel):
    """A client allowed ``terminal`` alone, its session open, and its row gone
    after."""
    status, made = panel.call(
        "POST", "/hub/client/enrollment/create", {"name": "integration-exec"}
    )
    if status == 400 and made.get("detail", {}).get("code") == "no_reachable_address":
        pytest.skip("this box exposes no address a client could be sent to")
    assert status == 200, made
    addresses, ticket, hub_key = connect_probe.parse_client_link(made["link"])
    client = connect_probe.Client()
    client.start()
    try:
        client.join(addresses, ticket, hub_key)
        status, answer = panel.call(
            "POST",
            "/hub/client/permission/set",
            {"client_id": client.binding_id, "kinds": ["terminal"]},
        )
        assert status == 200, answer
        client.dial()
        yield client
    finally:
        client.leave()
        client.close()
        for row in panel.read("/hub/client")["clients"]:
            if row["id"] == client.binding_id:
                panel.call(
                    "POST", "/hub/client/remove", {"client_id": client.binding_id}
                )


@pytest.fixture
def machine(panel) -> dict:
    """The hub's own online agent, else the first online machine listed."""
    devices = panel.read("/hub/device/online")["devices"]
    if not devices:
        pytest.skip("no machine has its agent online")
    return next((device for device in devices if device["is_hub"]), devices[0])


def is_windows(device: dict) -> bool:
    return str((device.get("platform") or {}).get("os", "")).lower() == "windows"


def run_exec(client, device_id: str, argv: list, stdin: bytes) -> tuple:
    """Open one ``exec`` on the machine, send the stdin, and read to the close.

    Returns:
        The bytes by output, ``{"data", "stderr"}``, and the close's
        ``{code, params}``.
    """
    return connect_probe.run_exec(
        client,
        {
            "device_id": device_id,
            "argv": argv,
            "is_tty": False,
            "cols": 80,
            "rows": 24,
        },
        stdin,
        EXEC_TIMEOUT_S,
    )


def test_stdout_and_stderr_arrive_apart_and_the_exit_code_comes_back(
    exec_client, machine
):
    argv = STDIO_ARGV_WINDOWS if is_windows(machine) else STDIO_ARGV

    received, close = run_exec(exec_client, machine["device_id"], argv, b"")

    assert close == {"code": "", "params": {"exit_code": 7}}, json.dumps(close)
    assert received["data"].strip() == b"out"
    assert received["stderr"].strip() == b"err"


def test_stdin_reaches_the_command_and_the_input_ended_frame_ends_it(
    exec_client, machine
):
    argv = CAT_ARGV_WINDOWS if is_windows(machine) else CAT_ARGV

    received, close = run_exec(exec_client, machine["device_id"], argv, b"hello")

    assert close == {"code": "", "params": {"exit_code": 0}}, json.dumps(close)
    assert received["data"].rstrip(b"\r\n") == b"hello"
    assert received["stderr"] == b""

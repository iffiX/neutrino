"""The control client: one request function over one Unix socket.

The happy path is exercised end to end by the server suite; here the two
ways a request has no answer to give back.
"""

import json
import socket
import threading

import pytest

from neutrino_agent.control import client


def serve_once(socket_path: str, response: bytes) -> threading.Thread:
    """Answer exactly one connection with canned bytes.

    Args:
        socket_path: Where to listen.
        response: What to write back.

    Returns:
        The serving thread, already started.
    """
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(socket_path)
    listener.listen(1)

    def serve() -> None:
        connection, _ = listener.accept()
        connection.recv(4096)
        connection.sendall(response)
        connection.close()
        listener.close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    return thread


def canned(body: bytes) -> bytes:
    return (
        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "
        + str(len(body)).encode()
        + b"\r\n\r\n"
        + body
    )


def test_a_request_carries_its_body_and_decodes_the_reply(tmp_path):
    path = str(tmp_path / "agent.sock")
    serve_once(path, canned(json.dumps({"version": "0.1.0"}).encode()))

    status, reply = client.request(
        socket_path=path,
        method="POST",
        path="/api/rdp/stop",
        body={"user": "alice"},
    )

    assert (status, reply) == (200, {"version": "0.1.0"})


def test_nothing_listening_is_an_os_error(tmp_path):
    with pytest.raises(OSError):
        client.request(
            socket_path=str(tmp_path / "absent.sock"),
            method="GET",
            path="/api/state",
        )


def test_a_reply_that_is_no_object_is_refused(tmp_path):
    path = str(tmp_path / "agent.sock")
    serve_once(path, canned(b"[]"))

    with pytest.raises(ValueError):
        client.request(socket_path=path, method="GET", path="/api/state")

"""The control client: one request function, dialed by the path's shape.

A Unix path opens the socket; a ``\\\\.\\pipe\\`` name opens the named
pipe. The socket side is exercised end to end by the server suite; here the
pipe side speaks HTTP through a scripted connection.
"""

import json

import pytest

import neutrino_client.platforms.windows_pipe as windows_pipe
from neutrino_client.control import client


class ScriptedPipeApi:
    """A client-end pipe that answers with one canned HTTP response."""

    def __init__(self, response: bytes):
        self.response = response
        self.position = 0
        self.sent = bytearray()
        self.closed = []
        self.opened = []

    def open_client(self, pipe_name):
        self.opened.append(pipe_name)
        return 31

    def read(self, handle, size):
        chunk = self.response[self.position : self.position + size]
        self.position += len(chunk)
        return chunk

    def write(self, handle, data):
        self.sent.extend(data)

    def close(self, handle):
        self.closed.append(handle)


def canned_response(payload: dict) -> bytes:
    body = json.dumps(payload).encode("utf-8")
    return (
        b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
        b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
    )


def test_a_pipe_path_dials_the_named_pipe(monkeypatch):
    api = ScriptedPipeApi(canned_response({"hostname": "box"}))

    def open_scripted(pipe_name, **kwargs):
        return windows_pipe.PipeConnection(
            api=api, handle=api.open_client(pipe_name), is_server_end=False
        )

    monkeypatch.setattr(windows_pipe, "open_pipe_connection", open_scripted)

    status, reply = client.request(
        socket_path="\\\\.\\pipe\\neutrino_client_alice",
        method="POST",
        path="/api/services/port",
        body={"id": "svc_tcp"},
    )

    assert (status, reply) == (200, {"hostname": "box"})
    sent = bytes(api.sent)
    assert sent.startswith(b"POST /api/services/port HTTP/1.1\r\n")
    assert b'{"id": "svc_tcp"}' in sent
    assert api.opened == ["\\\\.\\pipe\\neutrino_client_alice"]
    assert api.closed == [31]


def test_a_pipe_that_answers_no_object_is_refused(monkeypatch):
    api = ScriptedPipeApi(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n[]")

    def open_scripted(pipe_name, **kwargs):
        return windows_pipe.PipeConnection(
            api=api, handle=api.open_client(pipe_name), is_server_end=False
        )

    monkeypatch.setattr(windows_pipe, "open_pipe_connection", open_scripted)

    with pytest.raises(ValueError):
        client.request(
            socket_path="\\\\.\\pipe\\neutrino_client_alice",
            method="GET",
            path="/api/state",
        )

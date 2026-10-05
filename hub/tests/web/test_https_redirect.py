"""Where the HTTP port sends a browser while HTTPS is on.

The route-level walk, a request answered 301 and the authority still served,
is in ``routers/hub/test_setting.py``; this pins the address itself, and
that a plain request from loopback is served whatever the setting says.
"""

import asyncio

import pytest

from neutrino_hub.web.https_redirect import (
    PanelHttpsRedirectMiddleware,
    https_location,
    is_loopback_peer,
)


@pytest.mark.parametrize(
    "host, https_port, path, query, expected",
    [
        ("192.168.8.1:8080", 443, "/", "", "https://192.168.8.1/"),
        ("192.168.8.1", 8444, "/devices", "", "https://192.168.8.1:8444/devices"),
        (
            "hub.neutrino.internal:80",
            443,
            "/a",
            "b=c",
            "https://hub.neutrino.internal/a?b=c",
        ),
        ("[fd00::1]:8080", 8444, "/", "", "https://[fd00::1]:8444/"),
        ("argon", 443, "", "", "https://argon/"),
    ],
)
def test_the_address_keeps_the_host_and_path_on_the_https_port(
    host, https_port, path, query, expected
):
    assert https_location(host, https_port, path, query) == expected


class SettingsRuntime:
    def __init__(self, is_https_enabled: bool):
        self.settings = {
            "is_https_enabled": is_https_enabled,
            "listen_port": 8080,
            "https_listen_port": 443,
        }


def answered(is_https_enabled: bool, scheme: str, peer: str) -> int:
    """The status one request gets: 200 when the panel serves it, else 301."""
    sent: list = []

    async def panel(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    async def send(message):
        sent.append(message)

    async def receive():
        return {"type": "http.request", "body": b""}

    middleware = PanelHttpsRedirectMiddleware(
        panel, runtime=SettingsRuntime(is_https_enabled)
    )
    scope = {
        "type": "http",
        "scheme": scheme,
        "path": "/",
        "raw_path": b"/",
        "query_string": b"",
        "headers": [(b"host", b"hub.neutrino.internal:8080")],
        "client": (peer, 40000),
    }
    asyncio.run(middleware(scope, receive, send))
    return sent[0]["status"]


def test_a_plain_request_from_loopback_is_served_while_https_is_on():
    assert answered(True, "http", "127.0.0.1") == 200
    assert answered(True, "http", "::1") == 200
    assert answered(True, "http", "192.168.8.20") == 301
    assert answered(False, "https", "127.0.0.1") == 301


@pytest.mark.parametrize(
    ("peer", "is_loopback"),
    [
        ("127.0.0.1", True),
        ("::1", True),
        ("::ffff:127.0.0.1", True),
        ("::ffff:192.168.8.20", False),
        ("::127.0.0.1", False),
        ("192.168.8.20", False),
        ("not an address", False),
    ],
)
def test_only_a_loopback_peer_or_its_mapped_form_is_loopback(peer, is_loopback):
    assert is_loopback_peer({"client": (peer, 5000)}) is is_loopback

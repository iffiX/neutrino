"""Where the HTTP port sends a browser while HTTPS is on.

The route-level walk, a request answered 301 and the authority still served,
is in ``routers/hub/test_setting.py``; this pins the address itself.
"""

import pytest

from neutrino_hub.web.https_redirect import https_location


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

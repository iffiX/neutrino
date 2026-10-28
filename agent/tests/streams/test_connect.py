"""Which ports this machine publishes now, as the transport's ``port`` question reads them.

What these pin: each kind of published port is in the table while it is
published and gone once it is not: the file share's 445 while it reports a
share, the desktop's direct port while it is shared, Gitea's port and its
own SSH server's while it reports a url, each configured account program's
port from its details, each running SSH server instance's, a container
module's forwarder port from its details, and each port a running container
publishes, to the one address it is published on; UDP holds the
containers' UDP ports alone; a hub container's page port is never one.
"""

import pytest

from neutrino_agent.streams.connect import dial_address, published_ports, url_port

SAMBA = {"state": "running", "details": {"shares": [{"name": "media"}]}}
GITEA = {
    "state": "running",
    "details": {"url": "http://127.0.0.1:3000/", "port": 3000, "ssh_listen_port": 2222},
}
PODMAN = {
    "state": "running",
    "details": {
        "containers": [
            {
                "name": "db",
                "is_running": True,
                "host_bindings": [
                    {"address": "192.168.1.5", "port": 5432},
                    {"address": "", "port": 8080},
                    {"address": "0.0.0.0", "port": 8081},
                    {"address": "", "port": 5353, "protocol": "udp"},
                ],
            }
        ]
    },
}
INSTANCES = {
    name: {
        "state": "running",
        "details": {"instances": [{"account": "a", "port": port}]},
    }
    for name, port in (
        ("vscode", 8000),
        ("cloudcli", 3001),
        ("code_server", 8444),
        ("codeg", 3101),
    )
}
SSH_SERVER = {
    "state": "running",
    "details": {
        "instances": [
            {"account": "a", "port": 22000, "is_running": True},
            {"account": "b", "port": 22001, "is_running": False},
        ]
    },
}
HERMES = {"state": "running", "details": {"version": "0.52.492", "port": 8787}}
AYAKALEAF = {
    "state": "running",
    "details": {"version": "6.3.2", "port": 8900, "guests": []},
}
DESKTOP = {"is_shared": True, "port": 21118}


def everything() -> dict:
    return dict(
        INSTANCES,
        samba=SAMBA,
        gitea=GITEA,
        podman=PODMAN,
        ssh_server=SSH_SERVER,
        hermes_webui=HERMES,
        ayakaleaf=AYAKALEAF,
    )


def test_every_kind_of_published_port_is_in_the_table():
    ports = published_ports(everything(), {}, DESKTOP)

    assert ports == {
        445: "127.0.0.1",
        21118: "127.0.0.1",
        3000: "127.0.0.1",
        2222: "127.0.0.1",
        8000: "127.0.0.1",
        3001: "127.0.0.1",
        8444: "127.0.0.1",
        3101: "127.0.0.1",
        22000: "127.0.0.1",
        8787: "127.0.0.1",
        8900: "127.0.0.1",
        5432: "192.168.1.5",
        8080: "127.0.0.1",
        8081: "127.0.0.1",
    }


def test_udp_holds_the_containers_udp_ports_alone():
    assert published_ports(everything(), {}, DESKTOP, "udp") == {5353: "127.0.0.1"}


@pytest.mark.parametrize("state", ["installed", "absent", "failed", "installing"])
def test_a_module_the_hub_has_not_configured_publishes_nothing(state):
    unconfigured = {
        name: dict(entry, state=state) for name, entry in everything().items()
    }

    assert published_ports(unconfigured, {}, {"is_shared": False, "port": 21118}) == {}


def test_a_stopped_module_still_publishes_its_configured_ports():
    stopped = {name: dict(entry, state="stopped") for name, entry in INSTANCES.items()}

    assert set(published_ports(stopped, {}, None)) == {8000, 3001, 8444, 3101}


def test_a_port_not_taken_yet_is_no_port():
    waiting = {
        "vscode": {"state": "running", "details": {"instances": [{"account": "a"}]}},
        "hermes_webui": {"state": "running", "details": {"port": 0}},
        "gitea": {"state": "running", "details": {"url": "", "ssh_listen_port": 0}},
    }

    assert published_ports(waiting, {}, None) == {}


def test_a_stopped_containers_ports_are_not_published():
    stopped = {
        "state": "running",
        "details": {
            "containers": [
                {
                    "name": "db",
                    "is_running": False,
                    "host_bindings": [{"address": "", "port": 8080}],
                }
            ]
        },
    }

    assert published_ports({"podman": stopped}, {}, None) == {}


def test_a_gitea_url_with_no_port_publishes_its_schemes():
    gitea = {"state": "running", "details": {"url": "https://git.example/"}}

    assert published_ports({"gitea": gitea}, {}, {}) == {443: "127.0.0.1"}


@pytest.mark.parametrize(
    "url, port",
    [("http://h:81/", 81), ("https://h/", 443), ("http://h/", 80), ("ftp://h/", 0)],
)
def test_a_urls_port_is_its_own_or_its_schemes(url, port):
    assert url_port(url) == port


@pytest.mark.parametrize(
    "address, dialled",
    [
        ("", "127.0.0.1"),
        ("0.0.0.0", "127.0.0.1"),
        ("::", "127.0.0.1"),
        ("192.168.1.5", "192.168.1.5"),
    ],
)
def test_a_port_published_on_one_address_is_dialled_there(address, dialled):
    assert dial_address(address) == dialled


def test_the_port_a_hub_container_s_page_is_published_at_is_never_served():
    podman = {
        "state": "running",
        "details": {
            "containers": [
                {
                    "name": "neutrino_demo",
                    "module": "demo",
                    "is_running": True,
                    "ports": ["40123:8787", "9000:9000"],
                    "host_bindings": [
                        {"address": "127.0.0.1", "port": 40123},
                        {"address": "", "port": 9000},
                    ],
                }
            ]
        },
    }
    desired = {
        "podman": {
            "want": "running",
            "config": {
                "hub_containers": [
                    {"module": "demo", "name": "neutrino_demo", "page_port": 8787}
                ]
            },
        }
    }

    assert published_ports({"podman": podman}, desired, None) == {9000: "127.0.0.1"}
    assert published_ports({"podman": podman}, {}, None) == {
        40123: "127.0.0.1",
        9000: "127.0.0.1",
    }

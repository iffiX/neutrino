"""What a module's report amounts to as the hub's configuration.

Each import is a pure function of ``details``: Samba's shares and users in
the hub's shape, a share with no path left out and ``valid users`` kept to
the names the user list carries; Podman's containers with a unit read as
autostart, each container's services and the Podman machine's account, with
its disk's size now as the limit, taken where they are reported; Gitea's
nothing; and a module with no import answering empty.
"""

import pytest

from neutrino_hub.modules.devices.module_import import (
    MODULE_IMPORTS,
    gitea_import_config,
    import_module_config,
    podman_import_config,
    samba_import_config,
)


def test_samba_copies_nothing_of_what_the_machine_serves():
    details = {
        "shares": [
            {
                "name": "media",
                "path": "/srv/media",
                "params": {"read only": "Yes", "valid users": "alice, carol bob"},
            }
        ],
        "users": [{"name": "alice", "is_present": True, "has_password": True}],
    }

    assert samba_import_config(details) == {"shares": [], "users": []}


def test_samba_with_nothing_served_amounts_to_an_empty_list_of_each():
    assert samba_import_config({}) == {"shares": [], "users": []}


def test_podman_reads_the_containers_and_the_mirrors():
    details = {
        "containers": [
            {
                "name": "web",
                "image": "docker.io/nginx:1.27",
                "ports": ["8080:80"],
                "volumes": ["/srv/web:/usr/share/nginx/html"],
                "environment": ["TZ=UTC"],
                "has_unit": True,
            },
            {"name": "", "image": "x"},
            {"name": "shell", "image": "alpine"},
        ],
        "mirrors": ["https://mirror.example"],
    }

    assert podman_import_config(details) == {
        "containers": [
            {
                "name": "web",
                "image": "docker.io/nginx:1.27",
                "ports": ["8080:80"],
                "volumes": ["/srv/web:/usr/share/nginx/html"],
                "environment": ["TZ=UTC"],
                "command": "",
                "is_autostart": True,
            },
            {
                "name": "shell",
                "image": "alpine",
                "ports": [],
                "volumes": [],
                "environment": [],
                "command": "",
                "is_autostart": False,
            },
        ],
        "mirrors": ["https://mirror.example"],
    }


def test_podman_takes_the_services_and_the_machines_account_where_reported():
    details = {
        "containers": [
            {
                "name": "web",
                "image": "nginx",
                "ports": ["8080:80", "5353:53"],
                "has_unit": True,
                "services": [
                    {"port": 8080, "kind": "web", "scheme": "https"},
                    {"port": 5353, "kind": "port", "protocols": ["tcp", "udp"]},
                    "not a service",
                ],
            },
            {"name": "shell", "image": "alpine"},
        ],
        "machine": {
            "account": "lab",
            "is_running": True,
            "cpus": 8,
            "memory_gib": 4,
            "disk_gib": 100,
        },
    }

    imported = podman_import_config(details)

    assert imported["containers"][0]["services"] == [
        {"port": 8080, "kind": "web", "scheme": "https", "protocols": []},
        {"port": 5353, "kind": "port", "scheme": "http", "protocols": ["tcp", "udp"]},
    ]
    assert "services" not in imported["containers"][1]
    assert imported["machine"] == {
        "account": "lab",
        "login_id": "",
        "cpus": 0,
        "memory_gib": 0,
        "disk_gib": 100,
    }


@pytest.mark.parametrize(
    "reported, disk_gib", [(119.2, 120), (0, 0), (None, 0), ("many", 0)]
)
def test_podman_takes_the_machines_disk_now_as_its_limit(reported, disk_gib):
    details = {"machine": {"account": "lab", "disk_gib": reported}}

    assert podman_import_config(details)["machine"]["disk_gib"] == disk_gib


def test_podman_takes_no_machine_without_a_reported_account():
    assert "machine" not in podman_import_config({"machine": {"account": ""}})
    assert "machine" not in podman_import_config({"machine": "lab"})
    assert "machine" not in podman_import_config({})


def test_gitea_imports_nothing():
    assert gitea_import_config({"url": "http://192.168.100.7:3000"}) == {}


def test_a_module_is_imported_by_name_and_one_with_no_import_answers_empty():
    assert set(MODULE_IMPORTS) == {"samba", "gitea", "podman"}
    assert import_module_config("samba", {"users": [{"name": "alice"}]}) == {
        "shares": [],
        "users": [],
    }
    assert import_module_config("vscode", {"instances": []}) == {}
    assert import_module_config("rustdesk", {}) == {}


def test_podman_leaves_out_a_container_with_a_module_s_label():
    details = {
        "containers": [
            {"name": "web", "image": "nginx", "module": ""},
            {"name": "neutrino_demo", "image": "ghcr.io/acme/demo", "module": "demo"},
        ],
        "mirrors": [],
    }

    names = [c["name"] for c in podman_import_config(details)["containers"]]

    assert names == ["web"]

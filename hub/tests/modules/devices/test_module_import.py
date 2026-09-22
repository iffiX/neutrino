"""What a module's report amounts to as the hub's configuration.

Each import is a pure function of ``details``: Samba's shares and users in
the hub's shape, a share with no path left out and ``valid users`` kept to
the names the user list carries; Podman's containers with a unit read as
autostart; Gitea's nothing; and a module with no import answering empty.
"""

from neutrino_hub.modules.devices.module_import import (
    MODULE_IMPORTS,
    gitea_import_config,
    import_module_config,
    podman_import_config,
    samba_import_config,
)


def test_samba_reads_the_shares_and_users_into_the_hubs_shape():
    details = {
        "shares": [
            {
                "name": "media",
                "path": "/srv/media",
                "params": {
                    "comment": "films",
                    "read only": "Yes",
                    "valid users": "alice, carol bob",
                },
            },
            {"name": "printers", "path": "", "params": {}},
            "not a share",
        ],
        "users": [
            {"name": "alice", "is_present": True, "has_password": True},
            {"name": "bob", "is_present": True, "has_password": False},
            {"is_present": True},
        ],
    }

    assert samba_import_config(details) == {
        "shares": [
            {
                "name": "media",
                "path": "/srv/media",
                "comment": "films",
                "is_read_only": True,
                "valid_users": ["alice", "bob"],
            }
        ],
        "users": ["alice", "bob"],
    }


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


def test_gitea_imports_nothing():
    assert gitea_import_config({"url": "http://192.168.100.7:3000"}) == {}


def test_a_module_is_imported_by_name_and_one_with_no_import_answers_empty():
    assert set(MODULE_IMPORTS) == {"samba", "gitea", "podman"}
    assert import_module_config("samba", {"users": [{"name": "alice"}]}) == {
        "shares": [],
        "users": ["alice"],
    }
    assert import_module_config("zfs", {"pools": [{"name": "tank"}]}) == {}
    assert import_module_config("rustdesk", {}) == {}

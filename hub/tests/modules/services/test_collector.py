"""The apps and the typed service list: what each device's module publishes.

What these pin, against protocol.md's "Apps" and "The local name and the
local port": a program's instance is one app with one ``web`` entry; Gitea
is one app with ``web`` and ``ssh``, the latter a TCP ``port`` entry; the SSH
server is one app with one ``ssh`` entry per instance, in the module's
order; a container module's page is its app; a container the hub does not
manage is an app of its own, ``declared`` or ``manual``; a declared app's
entries are named ``web_<port>``, ``port_<port>[_udp]`` and ``file_<slug>``
and carry the probe's health and detail; every app entry's id is ``<app
id>_<name>``, its local port follows from that id alone and lies in 24000 to
31999; a local name is the app's slug, the machine's slug and
``.localhost``, two machines of one slug told apart by their ids; the ``ai``,
``rdp`` and a machine's ``file`` entries belong to no app; and a payload's
host is rewritten for the caller's scope.
"""

import hashlib

from neutrino_hub.modules.services.apps import (
    app_slugs,
    cookie_name,
    entry_id,
    local_name,
    local_port,
    machine_slugs,
    slug,
)
from neutrino_hub.modules.services.collector import (
    ServiceListCollector,
    catalog_entries,
    resolve_entries,
)
from neutrino_hub.modules.services.config import DeclaredApp, DeclaredEntry
from neutrino_hub.modules.services.device_shares import DeviceShare
from neutrino_hub.modules.services.probe import DeclaredEntryHealth

DEVICE = "d1d1d1d1d1d1d1d1"
HOST = "192.168.100.7"


def collector(**fields) -> ServiceListCollector:
    base = {
        "hub_host": "192.168.100.1",
        "is_ai_served": False,
        "ai_port": 8317,
        "ai_models": [],
        "is_ai_healthy": False,
        "device_modules": [],
        "declared_apps": [],
        "declared_healths": {},
        "device_names": {DEVICE: "Argon Box"},
        "machine_slugs": machine_slugs({DEVICE: "Argon Box"}),
    }
    base.update(fields)
    return ServiceListCollector(**base)


def by_id(entries: list) -> dict:
    return {entry["id"]: entry for entry in entries}


def test_the_local_port_follows_from_the_entry_id_alone_inside_the_range():
    digest = hashlib.sha256(b"gitea_abc_ssh").digest()
    expected = 24000 + int.from_bytes(digest[:4], "big") % 8000

    assert local_port("gitea_abc_ssh") == expected
    assert 24000 <= local_port("x") < 32000
    assert entry_id("gitea_abc", "ssh") == "gitea_abc_ssh"
    assert (
        cookie_name("gitea_abc_web")
        == "neutrino_" + hashlib.sha256(b"gitea_abc_web").hexdigest()[:12]
    )


def test_a_slug_is_lowercase_runs_of_letters_and_digits_joined_by_one_dash():
    assert slug("Argon  Box!") == "argon-box"
    assert slug("---") == "app"
    assert slug("x" * 80).__len__() == 63
    assert local_name("codeg-ann", "argon") == "codeg-ann.argon.localhost"


def test_two_machines_of_one_slug_are_told_apart_by_their_ids():
    slugs = machine_slugs(
        {"a1b2c3d4e5f6": "Box", "f6e5d4c3b2a1": "box", "abc": "Other"}  # scan: allow
    )

    assert slugs == {
        "a1b2c3d4e5f6": "box-a1b2c3",
        "f6e5d4c3b2a1": "box-f6e5d4",
        "abc": "other",
    }
    assert app_slugs({"codeg_d_ann": "Codeg (ann)", "codeg_d_bob": "Codeg (bob)"}) == {
        "codeg_d_ann": "codeg-ann",
        "codeg_d_bob": "codeg-bob",
    }


def test_a_programs_instance_is_one_app_with_one_web_entry():
    entries = collector(
        device_modules=[
            {
                "device_id": DEVICE,
                "host": HOST,
                "codeg": {
                    "instances": [{"account": "ann", "port": 3101, "is_healthy": True}]
                },
            }
        ]
    ).render()
    apps = collector(
        device_modules=[
            {
                "device_id": DEVICE,
                "host": HOST,
                "codeg": {
                    "instances": [{"account": "ann", "port": 3101, "is_healthy": True}]
                },
            }
        ]
    ).apps()

    (entry,) = entries
    app_id = f"codeg_{DEVICE}_ann"
    assert entry["id"] == f"{app_id}_web"
    assert (entry["app_id"], entry["name"], entry["type"]) == (app_id, "web", "web")
    assert entry["payload"] == {
        "url": f"http://{HOST}:3101/",
        "is_token_required": True,
    }
    assert entry["local_port"] == local_port(entry["id"])
    assert entry["description_code"] == "codeg_module"
    assert entry["description_params"] == {"host": HOST, "account": "ann"}
    assert apps == [
        {
            "id": app_id,
            "title": "Codeg (ann)",
            "source": "module",
            "device_id": DEVICE,
            "device_name": "Argon Box",
            "local_name": "codeg-ann.argon-box.localhost",
            "description": "",
        }
    ]


def test_gitea_is_one_app_with_a_web_entry_and_a_tcp_port_entry_for_its_ssh():
    entries = by_id(
        collector(
            device_modules=[
                {
                    "device_id": DEVICE,
                    "host": HOST,
                    "gitea": {
                        "is_healthy": True,
                        "url": f"http://{HOST}:3000/",
                        "ssh_listen_port": 2222,
                    },
                }
            ]
        ).render()
    )

    app_id = f"gitea_{DEVICE}"
    assert set(entries) == {f"{app_id}_web", f"{app_id}_ssh"}
    assert entries[f"{app_id}_ssh"]["type"] == "port"
    assert entries[f"{app_id}_ssh"]["payload"] == {
        "host": HOST,
        "port": 2222,
        "protocol": "tcp",
    }
    assert entries[f"{app_id}_web"]["payload"] == {"url": f"http://{HOST}:3000/"}


def test_the_ssh_server_is_one_app_with_an_ssh_entry_per_instance_in_order():
    entries = collector(
        device_modules=[
            {
                "device_id": DEVICE,
                "host": HOST,
                "ssh_server": {
                    "host_key_fingerprint": "SHA256:abc",
                    "instances": [
                        {"account": "bob", "port": 22001, "is_healthy": True},
                        {"account": "ann", "port": 22002, "is_healthy": False},
                    ],
                },
            }
        ]
    ).render()

    assert [entry["id"] for entry in entries] == [
        f"ssh_server_{DEVICE}_bob",
        f"ssh_server_{DEVICE}_ann",
    ]
    assert entries[0]["type"] == "ssh"
    assert entries[0]["payload"] == {
        "host": HOST,
        "port": 22001,
        "account": "bob",
        "host_key_fingerprint": "SHA256:abc",
    }
    assert entries[0]["title"] == "SSH (bob)"
    assert entries[1]["is_healthy"] is False
    assert entries[0]["description_code"] == "ssh_server_module"


def test_a_containers_ports_are_an_app_of_its_own_declared_or_manual():
    entries = by_id(
        collector(
            device_modules=[
                {
                    "device_id": DEVICE,
                    "host": HOST,
                    "podman": {
                        "containers": [
                            {
                                "name": "kuma",
                                "image": "louislam/uptime-kuma",
                                "is_running": True,
                                "source": "declared",
                                "bindings": [(3001, "tcp", "http"), (5353, "udp", "")],
                            },
                            {
                                "name": "mine",
                                "image": "x",
                                "is_running": False,
                                "source": "manual",
                                "bindings": [(25565, "tcp", "")],
                            },
                        ]
                    },
                }
            ]
        ).render()
    )

    assert set(entries) == {
        f"podman_{DEVICE}_kuma_3001",
        f"podman_{DEVICE}_kuma_5353_udp",
        f"podman_{DEVICE}_mine_25565",
    }
    assert entries[f"podman_{DEVICE}_kuma_3001"]["type"] == "web"
    assert entries[f"podman_{DEVICE}_kuma_3001"]["source"] == "declared"
    assert entries[f"podman_{DEVICE}_kuma_5353_udp"]["payload"]["protocol"] == "udp"
    assert entries[f"podman_{DEVICE}_mine_25565"]["source"] == "manual"
    assert entries[f"podman_{DEVICE}_mine_25565"]["is_healthy"] is False


def test_hermes_webui_is_one_app_with_its_page_alone():
    held = collector(
        device_modules=[
            {
                "device_id": DEVICE,
                "host": HOST,
                "hermes_webui": {"port": 8787, "is_healthy": True},
            }
        ]
    )

    (entry,) = held.render()
    (app,) = held.apps()
    assert entry["id"] == f"hermes_webui_{DEVICE}_web"
    assert entry["payload"] == {
        "url": f"http://{HOST}:8787/",
        "is_token_required": True,
    }
    assert app["title"] == "Hermes WebUI"
    assert app["local_name"] == "hermes-webui.argon-box.localhost"


def test_a_declared_apps_entries_are_named_by_their_type_and_port():
    app = DeclaredApp(
        id="app1",
        name="NAS",
        host="192.168.100.50",
        description="",
        created_at="",
        entries=[
            DeclaredEntry(type="web", port=443, scheme="https", path="/ui"),
            DeclaredEntry(type="port", port=53, protocol="udp"),
            DeclaredEntry(type="file", port=445, share="Media Files"),
        ],
    )
    healths = {
        "app1_web_443": DeclaredEntryHealth("app1_web_443", True, "t", None),
        "app1_file_media-files": DeclaredEntryHealth(
            "app1_file_media-files", False, "t", "share_missing"
        ),
    }
    held = collector(declared_apps=[app], declared_healths=healths)

    entries = by_id(held.render())
    assert set(entries) == {"app1_web_443", "app1_port_53_udp", "app1_file_media-files"}
    assert entries["app1_web_443"]["payload"] == {
        "url": "https://192.168.100.50:443/ui"
    }
    assert entries["app1_web_443"]["is_healthy"] is True
    assert entries["app1_port_53_udp"]["is_healthy"] is None
    assert entries["app1_file_media-files"]["detail_code"] == "share_missing"
    assert entries["app1_file_media-files"]["payload"]["share"] == "Media Files"
    assert entries["app1_file_media-files"]["app_id"] == "app1"
    assert entries["app1_web_443"]["description_code"] == "declared"
    (declared,) = held.apps()
    assert declared["source"] == "declared"
    assert declared["local_name"] == "nas.machine.localhost"


def test_the_ai_rdp_and_a_machines_file_entries_belong_to_no_app():
    held = collector(
        is_ai_served=True,
        ai_models=["gpt"],
        is_ai_healthy=True,
        device_modules=[
            {
                "device_id": DEVICE,
                "host": HOST,
                "samba": {
                    "is_healthy": True,
                    "shares": [{"name": "ann", "user": "neutrino-ann"}],
                },
            }
        ],
        device_shares=[
            DeviceShare(
                share_id="s1",
                device_id=DEVICE,
                host=HOST,
                hostname="argon",
                port=21118,
                platform_os="linux",
                declared_at=0.0,
            )
        ],
    )

    entries = by_id(held.render())
    assert set(entries) == {"ai", f"samba_{DEVICE}_ann", "rdp_s1"}
    assert all(entry["app_id"] == "" for entry in entries.values())
    assert entries[f"samba_{DEVICE}_ann"]["payload"]["users"] == ["neutrino-ann"]
    assert held.apps() == []
    catalog = catalog_entries(list(entries.values()))
    assert set(catalog[0]) == {
        "id",
        "type",
        "title",
        "payload",
        "is_healthy",
        "source",
        "description",
        "description_code",
        "description_params",
        "app_id",
        "name",
        "local_port",
    }


def test_entries_are_resolved_per_scope_and_the_hubs_own_take_the_hubs_address():
    entries = collector(
        is_ai_served=True,
        ai_models=[],
        device_modules=[
            {
                "device_id": DEVICE,
                "host": HOST,
                "hermes_webui": {"port": 8787, "is_healthy": True},
            }
        ],
    ).render()

    resolved = by_id(
        resolve_entries(
            entries,
            device_hosts={DEVICE: "100.64.0.7"},
            hub_addresses={"192.168.100.1"},
            hub_host="100.64.0.1",
        )
    )

    assert resolved[f"hermes_webui_{DEVICE}_web"]["payload"]["url"] == (
        "http://100.64.0.7:8787/"
    )
    assert resolved["ai"]["payload"]["endpoint"] == "http://100.64.0.1:8317"
    assert by_id(entries)["ai"]["payload"]["endpoint"] == "http://192.168.100.1:8317"

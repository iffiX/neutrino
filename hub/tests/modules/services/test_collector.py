"""The typed service list: what each device's module publishes, and how hosts resolve."""

from neutrino_hub.modules.services.collector import (
    ServiceListCollector,
    catalog_entries,
    hub_self_addresses,
    resolve_entries,
)
from neutrino_hub.modules.services.config import DeclaredService, DeclaredShare
from neutrino_hub.modules.services.device_shares import DeviceShare
from neutrino_hub.modules.services.probe import DeclaredServiceHealth

HUB = "192.168.100.1"
DEVICE = "aa:bb:cc:dd:ee:ff"
DEVICE_HOST = "192.168.100.7"


def collect(**overrides) -> list[dict]:
    fields = {
        "hub_host": HUB,
        "is_ai_served": False,
        "ai_port": 8317,
        "ai_models": [],
        "is_ai_healthy": False,
        "device_modules": [],
        "declared_services": [],
        "declared_healths": {},
        "device_shares": [],
    }
    fields.update(overrides)
    return ServiceListCollector(**fields).render()


def hosting(*, device_id=DEVICE, host=DEVICE_HOST, samba=None, gitea=None, podman=None):
    return {
        "device_id": device_id,
        "host": host,
        "samba": samba,
        "gitea": gitea,
        "podman": podman,
    }


def container(name: str, *, ports: list[int], is_running: bool = True) -> dict:
    return {
        "name": name,
        "image": "docker.io/nginx:1.25",
        "is_running": is_running,
        "host_ports": ports,
    }


def health(record_id: str, is_healthy: bool | None, detail_code: str | None = None):
    return DeclaredServiceHealth(
        service_id=record_id,
        is_healthy=is_healthy,
        checked_at="2026-01-01T00:00:00+00:00",
        detail_code=detail_code,
    )


def declared(kind: str, **overrides) -> DeclaredService:
    fields = {
        "id": "r1",
        "name": "forge",
        "kind": kind,
        "host": "10.0.0.5",
        "port": 9000,
        "description": "the forge box",
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    fields.update(overrides)
    return DeclaredService(**fields)


def test_nothing_served_and_nothing_declared_is_an_empty_list():
    assert collect() == []


def test_a_devices_gitea_publishes_one_web_entry_only_while_served():
    entries = collect(
        device_modules=[
            hosting(gitea={"is_healthy": True, "url": f"http://{DEVICE_HOST}:3000/"})
        ]
    )
    assert [e["id"] for e in entries] == ["gitea_aa-bb-cc-dd-ee-ff"]
    entry = entries[0]
    assert entry["type"] == "web"
    assert entry["payload"] == {"url": f"http://{DEVICE_HOST}:3000/"}
    assert entry["is_healthy"] is True
    assert entry["source"] == "module"
    assert entry["record_id"] is None
    assert entry["description"] == f"published by the gitea module on {DEVICE_HOST}"

    assert collect(device_modules=[hosting(gitea=None)]) == []


def test_gitea_health_is_the_measured_answer_never_painted():
    entries = collect(
        device_modules=[hosting(gitea={"is_healthy": False, "url": "http://x:3000/"})]
    )
    assert entries[0]["is_healthy"] is False


def test_a_devices_samba_publishes_one_file_entry_per_share_at_its_address():
    entries = collect(
        device_modules=[
            hosting(samba={"is_healthy": True, "share_names": ["media", "backup"]})
        ]
    )
    assert [e["id"] for e in entries] == [
        "samba_aa-bb-cc-dd-ee-ff_media",
        "samba_aa-bb-cc-dd-ee-ff_backup",
    ]
    entry = entries[0]
    assert entry["type"] == "file"
    assert entry["payload"] == {
        "protocol": "smb",
        "host": DEVICE_HOST,
        "share": "media",
    }
    assert entry["source"] == "module"


def test_a_device_with_no_address_publishes_nothing_reachable():
    entries = collect(
        device_modules=[
            hosting(
                host="",
                samba={"is_healthy": True, "share_names": ["media"]},
                podman={"containers": [container("web", ports=[8080])]},
            )
        ]
    )
    assert entries == []


def test_the_ai_entry_carries_the_served_models_and_the_probe_health():
    entries = collect(
        is_ai_served=True,
        ai_models=["claude-sonnet-4-5", "gpt-5"],
        is_ai_healthy=True,
    )
    assert [e["id"] for e in entries] == ["ai"]
    entry = entries[0]
    assert entry["type"] == "ai"
    assert entry["payload"] == {
        "endpoint": f"http://{HUB}:8317",
        "protocol": "openai",
        "models": ["claude-sonnet-4-5", "gpt-5"],
    }
    assert entry["is_healthy"] is True


def test_a_devices_podman_publishes_one_port_entry_per_published_container_port():
    entries = collect(
        device_modules=[
            hosting(podman={"containers": [container("web", ports=[8080, 8443])]})
        ]
    )
    assert [e["id"] for e in entries] == [
        "podman_aa-bb-cc-dd-ee-ff_web_8080",
        "podman_aa-bb-cc-dd-ee-ff_web_8443",
    ]
    entry = entries[0]
    assert entry["type"] == "port"
    assert entry["payload"] == {"host": DEVICE_HOST, "port": 8080}
    assert entry["description"] == (
        f"published by container web (docker.io/nginx:1.25) on {DEVICE_HOST}"
    )


def test_a_stopped_container_publishes_its_port_as_unhealthy():
    entries = collect(
        device_modules=[
            hosting(
                podman={
                    "containers": [container("web", ports=[8080], is_running=False)]
                }
            )
        ]
    )
    assert entries[0]["is_healthy"] is False


def test_two_devices_publish_their_own_entries_side_by_side():
    entries = collect(
        device_modules=[
            hosting(samba={"is_healthy": True, "share_names": ["media"]}),
            hosting(
                device_id="11:22:33:44:55:66",
                host="192.168.100.8",
                samba={"is_healthy": False, "share_names": ["media"]},
            ),
        ]
    )
    assert [e["id"] for e in entries] == [
        "samba_aa-bb-cc-dd-ee-ff_media",
        "samba_11-22-33-44-55-66_media",
    ]
    assert [e["payload"]["host"] for e in entries] == [DEVICE_HOST, "192.168.100.8"]


def test_declared_records_map_onto_the_types_with_their_probe_health():
    records = [
        declared("http", id="w1", scheme="https", path="/status"),
        declared("generic_tcp", id="p1"),
        declared(
            "samba",
            id="f1",
            port=445,
            shares=[DeclaredShare(name="media"), DeclaredShare(name="backup")],
        ),
    ]
    entries = collect(
        declared_services=records,
        declared_healths={"w1": health("w1", True), "p1": health("p1", False)},
    )

    by_id = {e["id"]: e for e in entries}
    assert by_id["w1"]["type"] == "web"
    assert by_id["w1"]["payload"] == {"url": "https://10.0.0.5:9000/status"}
    assert by_id["w1"]["is_healthy"] is True
    assert by_id["w1"]["source"] == "declared"
    assert by_id["w1"]["description"] == "the forge box"
    assert by_id["p1"]["payload"] == {"host": "10.0.0.5", "port": 9000}
    assert by_id["p1"]["is_healthy"] is False
    assert by_id["f1_media"]["payload"]["share"] == "media"
    assert by_id["f1_media"]["record_id"] == "f1"
    assert by_id["f1_backup"]["record_id"] == "f1"
    assert by_id["w1"]["detail_code"] is None
    assert by_id["f1_media"]["is_healthy"] is None
    assert by_id["f1_media"]["detail_code"] is None


def test_every_row_of_a_record_carries_what_its_probe_measured():
    record = declared(
        "samba",
        id="f1",
        port=445,
        shares=[DeclaredShare(name="media"), DeclaredShare(name="backup")],
    )
    entries = collect(
        declared_services=[record],
        declared_healths={"f1": health("f1", False, "share_missing")},
    )

    assert [entry["detail_code"] for entry in entries] == [
        "share_missing",
        "share_missing",
    ]
    assert all(entry["is_healthy"] is False for entry in entries)


def test_a_module_entry_never_carries_a_detail_code():
    entries = collect(
        device_modules=[hosting(samba={"is_healthy": False, "share_names": ["media"]})]
    )

    assert entries[0]["source"] == "module"
    assert entries[0]["detail_code"] is None


def test_the_catalog_copy_drops_the_detail_code():
    record = declared("generic_tcp", id="p1")
    entries = collect(
        declared_services=[record],
        declared_healths={"p1": health("p1", False, "connect_failed")},
    )

    assert "detail_code" not in catalog_entries(entries)[0]


def test_resolution_substitutes_every_hub_self_host_for_the_caller_address():
    addresses = hub_self_addresses([HUB])
    entries = collect(
        is_ai_served=True,
        device_modules=[
            hosting(
                host=HUB,
                samba={"is_healthy": True, "share_names": ["media"]},
                gitea={"is_healthy": True, "url": f"http://{HUB}:3000/"},
                podman={"containers": [container("web", ports=[8080])]},
            )
        ],
        declared_services=[declared("generic_tcp", id="p1", host="127.0.0.1")],
        declared_healths={},
    )

    resolved = {
        e["id"]: e
        for e in resolve_entries(
            entries, hub_addresses=addresses, target_host="192.168.93.1"
        )
    }

    # A module hosted on the hub box's own agent sits at a hub address and
    # resolves like the hub's own.
    assert (
        resolved["gitea_aa-bb-cc-dd-ee-ff"]["payload"]["url"]
        == "http://192.168.93.1:3000/"
    )
    assert (
        resolved["samba_aa-bb-cc-dd-ee-ff_media"]["payload"]["host"] == "192.168.93.1"
    )
    assert resolved["ai"]["payload"]["endpoint"] == "http://192.168.93.1:8317"
    assert (
        resolved["podman_aa-bb-cc-dd-ee-ff_web_8080"]["payload"]["host"]
        == "192.168.93.1"
    )
    # A loopback host in a declaration is the hub's own by definition.
    assert resolved["p1"]["payload"]["host"] == "192.168.93.1"


def test_resolution_leaves_a_device_host_alone():
    entries = collect(
        device_modules=[
            hosting(
                samba={"is_healthy": True, "share_names": ["media"]},
                gitea={"is_healthy": True, "url": f"http://{DEVICE_HOST}:3000/"},
            )
        ]
    )

    resolved = {
        e["id"]: e
        for e in resolve_entries(
            entries, hub_addresses=hub_self_addresses([HUB]), target_host="192.168.93.1"
        )
    }

    assert resolved["samba_aa-bb-cc-dd-ee-ff_media"]["payload"]["host"] == DEVICE_HOST
    assert (
        resolved["gitea_aa-bb-cc-dd-ee-ff"]["payload"]["url"]
        == f"http://{DEVICE_HOST}:3000/"
    )


def test_resolution_leaves_a_foreign_host_alone():
    entries = collect(
        declared_services=[
            declared("generic_tcp", id="p1"),
            declared("http", id="w1", host="wiki.lan", scheme="http"),
        ],
        declared_healths={},
    )

    resolved = {
        e["id"]: e
        for e in resolve_entries(
            entries, hub_addresses=hub_self_addresses([HUB]), target_host="192.168.93.1"
        )
    }

    assert resolved["p1"]["payload"]["host"] == "10.0.0.5"
    assert resolved["w1"]["payload"]["url"] == "http://wiki.lan:9000/"


def test_the_catalog_copy_drops_the_panel_only_fields():
    entries = collect(declared_services=[declared("generic_tcp")], declared_healths={})

    stripped = catalog_entries(entries)

    assert set(stripped[0]) == {
        "id",
        "type",
        "title",
        "payload",
        "is_healthy",
        "source",
        "description",
        "description_code",
        "description_params",
    }


# --- the device source: a machine's own word that it is sharing ---


def share(share_id="s1", host="192.168.100.5", hostname="workshop", port=21118):
    return DeviceShare(
        share_id=share_id,
        mac_address="aa:bb:cc:dd:ee:ff",
        hostname=hostname,
        host=host,
        port=port,
        declared_at=0.0,
    )


def test_a_declaring_machine_publishes_one_rdp_entry():
    entries = collect(device_shares=[share()])

    assert len(entries) == 1
    entry = entries[0]
    assert entry["type"] == "rdp"
    assert entry["id"] == "rdp_s1"
    assert entry["title"] == "workshop"
    assert entry["payload"] == {
        "protocol": "rustdesk",
        "host": "192.168.100.5",
        "port": 21118,
        "attention": "",
    }


def test_an_rdp_entry_says_it_came_from_a_device():
    entry = collect(device_shares=[share()])[0]

    assert entry["source"] == "device"
    assert entry["description"] == "shared from workshop"


def test_no_declaration_publishes_no_rdp_entry():
    assert collect(device_shares=[]) == []
    assert collect() == []


def test_a_device_host_is_never_rewritten_to_the_hubs_own_address():
    entries = collect(device_shares=[share(host="192.168.100.5")])

    resolved = resolve_entries(
        entries, hub_addresses=hub_self_addresses([HUB]), target_host="10.0.0.9"
    )

    assert resolved[0]["payload"]["host"] == "192.168.100.5"


def test_the_catalog_carries_an_rdp_entry_whole():
    entries = catalog_entries(collect(device_shares=[share()]))

    assert entries[0]["source"] == "device"
    assert entries[0]["type"] == "rdp"
    assert "record_id" not in entries[0]


def test_two_machines_sharing_publish_one_entry_each():
    entries = collect(
        device_shares=[
            share(share_id="s1", hostname="workshop"),
            share(share_id="s2", hostname="studio", host="192.168.100.6"),
        ]
    )

    assert [entry["id"] for entry in entries] == ["rdp_s1", "rdp_s2"]


# --- provenance: the English line, and the code a page words itself ---


def test_every_composed_entry_names_where_it_came_from_in_a_code():
    entries = collect(
        device_modules=[
            hosting(
                gitea={"is_healthy": True, "url": f"http://{DEVICE_HOST}:3000/"},
                samba={"is_healthy": True, "share_names": ["media"]},
                podman={"containers": [container("web", ports=[8080])]},
            )
        ],
        is_ai_served=True,
        device_shares=[share()],
    )

    coded = {entry["id"]: entry for entry in entries}
    assert coded["gitea_aa-bb-cc-dd-ee-ff"]["description_code"] == "gitea_module"
    assert coded["gitea_aa-bb-cc-dd-ee-ff"]["description_params"] == {
        "host": DEVICE_HOST
    }
    assert coded["samba_aa-bb-cc-dd-ee-ff_media"]["description_code"] == "samba_module"
    assert coded["samba_aa-bb-cc-dd-ee-ff_media"]["description_params"] == {
        "host": DEVICE_HOST
    }
    port_id = "podman_aa-bb-cc-dd-ee-ff_web_8080"
    assert coded[port_id]["description_code"] == "container"
    assert coded[port_id]["description_params"] == {"image": "docker.io/nginx:1.25"}
    assert coded["ai"]["description_code"] == "ai_gateway"
    assert coded["ai"]["description_params"] == {}
    assert coded["rdp_s1"]["description_code"] == "device_share"
    assert coded["rdp_s1"]["description_params"] == {"device": "workshop"}


def test_a_declaration_with_its_own_line_keeps_it_and_carries_no_code():
    entry = collect(declared_services=[declared("generic_tcp")], declared_healths={})[0]

    assert entry["description"] == "the forge box"
    assert entry["description_code"] == ""


def test_a_declaration_with_no_line_of_its_own_says_it_was_declared():
    entry = collect(
        declared_services=[declared("generic_tcp", description="")],
        declared_healths={},
    )[0]

    assert entry["description"] == ""
    assert entry["description_code"] == "declared"
    assert entry["description_params"] == {}


def test_the_catalog_carries_the_code_and_its_params():
    entry = catalog_entries(collect(device_shares=[share()]))[0]

    assert entry["description_code"] == "device_share"
    assert entry["description_params"] == {"device": "workshop"}

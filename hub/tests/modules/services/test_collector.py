"""The typed service list: what each module publishes, and how hosts resolve."""

from neutrino_hub.modules.podman.ops import PodmanContainerState
from neutrino_hub.modules.services.collector import (
    ServiceListCollector,
    catalog_entries,
    hub_self_addresses,
    resolve_entries,
)
from neutrino_hub.modules.services.config import DeclaredService, DeclaredShare
from neutrino_hub.modules.services.probe import DeclaredServiceHealth

HUB = "192.168.100.1"


def collect(**overrides) -> list[dict]:
    fields = {
        "hub_host": HUB,
        "is_gitea_served": False,
        "gitea_url": "",
        "is_gitea_healthy": False,
        "is_samba_served": False,
        "samba_share_names": [],
        "is_samba_healthy": False,
        "is_ai_served": False,
        "ai_port": 8317,
        "ai_models": [],
        "is_ai_healthy": False,
        "is_podman_served": False,
        "podman_containers": [],
        "declared_services": [],
        "declared_healths": {},
    }
    fields.update(overrides)
    return ServiceListCollector(**fields).render()


def container(name: str, *, ports: list[int], is_running: bool = True):
    return PodmanContainerState(
        name=name,
        image="docker.io/nginx:1.25",
        status="Up 2 hours" if is_running else "Exited",
        is_running=is_running,
        is_declared=True,
        host_ports=ports,
    )


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


def test_gitea_publishes_one_web_entry_only_while_served():
    entries = collect(
        is_gitea_served=True,
        gitea_url=f"http://{HUB}:3000/",
        is_gitea_healthy=True,
    )
    assert [e["id"] for e in entries] == ["gitea"]
    entry = entries[0]
    assert entry["type"] == "web"
    assert entry["payload"] == {"url": f"http://{HUB}:3000/"}
    assert entry["is_healthy"] is True
    assert entry["source"] == "module"
    assert entry["record_id"] is None

    assert collect(is_gitea_served=False, gitea_url=f"http://{HUB}:3000/") == []


def test_gitea_health_is_the_measured_answer_never_painted():
    entries = collect(
        is_gitea_served=True,
        gitea_url=f"http://{HUB}:3000/",
        is_gitea_healthy=False,
    )
    assert entries[0]["is_healthy"] is False


def test_samba_publishes_one_file_entry_per_share_with_the_unit_health():
    entries = collect(
        is_samba_served=True,
        samba_share_names=["media", "backup"],
        is_samba_healthy=True,
    )
    assert [e["id"] for e in entries] == ["samba_media", "samba_backup"]
    entry = entries[0]
    assert entry["type"] == "file"
    assert entry["payload"] == {"protocol": "smb", "host": HUB, "share": "media"}
    assert entry["source"] == "module"


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


def test_every_entry_names_the_modules_it_cannot_work_without():
    entries = collect(
        is_gitea_served=True,
        gitea_url=f"http://{HUB}:3000/",
        is_gitea_healthy=True,
        is_samba_served=True,
        samba_share_names=["media"],
        is_samba_healthy=True,
        is_ai_served=True,
        is_podman_served=True,
        podman_containers=[container("web", ports=[8080])],
        declared_services=[
            declared("samba", id="n1", shares=[DeclaredShare(name="backup")])
        ],
        declared_healths={},
    )

    by_type = {}
    for entry in entries:
        by_type.setdefault(entry["type"], []).append(entry["modules"])
    # ai needs cc-switch, every file entry needs the mount tooling, and the
    # open-a-link types need nothing on the machine.
    assert by_type["ai"] == [["cc_switch"]]
    assert all(modules == ["samba_mount"] for modules in by_type["file"])
    assert len(by_type["file"]) >= 2
    assert all(modules == [] for modules in by_type["web"] + by_type["port"])


def test_podman_publishes_one_port_entry_per_published_container_port():
    entries = collect(
        is_podman_served=True,
        podman_containers=[container("web", ports=[8080, 8443])],
    )
    assert [e["id"] for e in entries] == ["podman_web_8080", "podman_web_8443"]
    entry = entries[0]
    assert entry["type"] == "port"
    assert entry["payload"] == {"host": HUB, "port": 8080}
    assert entry["description"] == "published by container web (docker.io/nginx:1.25)"


def test_a_stopped_container_publishes_its_port_as_unhealthy():
    entries = collect(
        is_podman_served=True,
        podman_containers=[container("web", ports=[8080], is_running=False)],
    )
    assert entries[0]["is_healthy"] is False


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
        declared_healths={
            "w1": health("w1", True),
            "p1": health("p1", False),
        },
    )

    by_id = {e["id"]: e for e in entries}
    assert by_id["w1"]["type"] == "web"
    assert by_id["w1"]["payload"] == {"url": "https://10.0.0.5:9000/status"}
    assert by_id["w1"]["is_healthy"] is True
    assert by_id["w1"]["source"] == "declared"
    assert by_id["w1"]["description"] == "the forge box"
    assert by_id["p1"]["payload"] == {"host": "10.0.0.5", "port": 9000}
    assert by_id["p1"]["is_healthy"] is False
    # One entry per share, both carrying the record's id for delete.
    assert by_id["f1_media"]["payload"]["share"] == "media"
    assert by_id["f1_media"]["record_id"] == "f1"
    assert by_id["f1_backup"]["record_id"] == "f1"
    assert by_id["w1"]["detail_code"] is None
    # Never probed reads None, not unhealthy.
    assert by_id["f1_media"]["is_healthy"] is None
    assert by_id["f1_media"]["detail_code"] is None


def test_every_row_of_a_record_carries_what_its_probe_measured():
    """A record's detail code reaches the page on each row it published."""
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
    """Health is the module's own, and it reports no probe reason."""
    entries = collect(
        is_samba_served=True,
        samba_share_names=["media"],
        is_samba_healthy=False,
    )

    assert entries[0]["source"] == "module"
    assert entries[0]["detail_code"] is None


def test_the_catalog_copy_drops_the_detail_code():
    """A device catalog carries health, not the panel's reason for it."""
    record = declared("generic_tcp", id="p1")
    entries = collect(
        declared_services=[record],
        declared_healths={"p1": health("p1", False, "connect_failed")},
    )

    assert "detail_code" not in catalog_entries(entries)[0]


def test_resolution_substitutes_every_hub_self_host_for_the_caller_address():
    addresses = hub_self_addresses([HUB])
    entries = collect(
        is_gitea_served=True,
        gitea_url=f"http://{HUB}:3000/",
        is_gitea_healthy=True,
        is_samba_served=True,
        samba_share_names=["media"],
        is_samba_healthy=True,
        is_ai_served=True,
        is_podman_served=True,
        podman_containers=[container("web", ports=[8080])],
        declared_services=[declared("generic_tcp", id="p1", host="127.0.0.1")],
        declared_healths={},
    )

    resolved = {
        e["id"]: e
        for e in resolve_entries(
            entries, hub_addresses=addresses, target_host="192.168.93.1"
        )
    }

    assert resolved["gitea"]["payload"]["url"] == "http://192.168.93.1:3000/"
    assert resolved["samba_media"]["payload"]["host"] == "192.168.93.1"
    assert resolved["ai"]["payload"]["endpoint"] == "http://192.168.93.1:8317"
    assert resolved["podman_web_8080"]["payload"]["host"] == "192.168.93.1"
    # A loopback host in a declaration is the hub's own by definition.
    assert resolved["p1"]["payload"]["host"] == "192.168.93.1"


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
            entries,
            hub_addresses=hub_self_addresses([HUB]),
            target_host="192.168.93.1",
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
        "modules",
    }

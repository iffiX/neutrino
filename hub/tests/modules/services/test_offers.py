"""The offer renderer: pure, secret-free, and stable in its ids."""

from neutrino_hub.modules.services.config import DeclaredService, DeclaredShare
from neutrino_hub.modules.services.docker import DockerContainer
from neutrino_hub.modules.services.offers import ServiceOfferRenderer


def render(**overrides) -> dict:
    """One rendered catalog half, with everything empty unless overridden."""
    inputs = {
        "hub_address": "192.168.100.1",
        "hub_share_names": [],
        "declared_services": [],
        "is_gitea_installed": False,
        "gitea_url": "",
        "docker_containers": {},
        "is_ai_served": False,
    }
    inputs.update(overrides)
    return ServiceOfferRenderer(**inputs).render()


def declared(kind: str, **overrides) -> DeclaredService:
    fields = {
        "id": "abc123",
        "name": "nas",
        "kind": kind,
        "host": "192.168.100.7",
        "port": 445,
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    fields.update(overrides)
    return DeclaredService(**fields)


def test_nothing_configured_renders_nothing():
    assert render() == {}


def test_a_hub_share_becomes_a_mount_offer():
    offers = render(hub_share_names=["media"])

    assert offers == {
        "hub_share_media": {
            "kind": "mount",
            "title": "media",
            "host": "192.168.100.1",
            "share": "media",
        }
    }


def test_a_hub_without_an_address_offers_no_hub_shares():
    assert render(hub_address="", hub_share_names=["media"]) == {}


def test_a_declared_samba_share_becomes_a_mount_offer():
    service = declared("samba", shares=[DeclaredShare(name="backups")])

    offers = render(declared_services=[service])

    assert offers == {
        "svc_abc123_backups": {
            "kind": "mount",
            "title": "backups",
            "host": "192.168.100.7",
            "share": "backups",
        }
    }


def test_a_mount_offer_never_carries_the_share_login():
    service = declared(
        "samba", shares=[DeclaredShare(name="backups", login_id="secret-login")]
    )

    offers = render(declared_services=[service])

    assert "login" not in str(offers)
    assert "secret" not in str(offers)


def test_a_declared_http_service_becomes_a_link_offer():
    service = declared("http", port=8080, scheme="https", path="/admin")

    offers = render(declared_services=[service])

    assert offers == {
        "svc_abc123": {
            "kind": "link",
            "title": "nas",
            "url": "https://192.168.100.7:8080/admin",
        }
    }


def test_an_http_service_without_a_path_links_to_the_root():
    service = declared("http", port=8080, scheme="http", path=None)

    offers = render(declared_services=[service])

    assert offers["svc_abc123"]["url"] == "http://192.168.100.7:8080/"


def test_gitea_links_only_when_installed():
    absent = render(is_gitea_installed=False, gitea_url="http://192.168.100.1:3000/")
    present = render(is_gitea_installed=True, gitea_url="http://192.168.100.1:3000/")

    assert absent == {}
    assert present == {
        "hub_gitea": {
            "kind": "link",
            "title": "Gitea",
            "url": "http://192.168.100.1:3000/",
        }
    }


def test_a_generic_tcp_service_becomes_a_port_offer():
    service = declared("generic_tcp", port=5432)

    offers = render(declared_services=[service])

    assert offers == {
        "svc_abc123": {
            "kind": "port",
            "title": "nas",
            "host": "192.168.100.7",
            "port": 5432,
        }
    }


def test_a_docker_container_offers_each_published_port():
    engine = declared("docker_engine", port=2375)
    containers = {
        "abc123": [
            DockerContainer(
                id="c1",
                name="web",
                image="nginx",
                state="running",
                is_running=True,
                host_ports=[8080, 8443],
            )
        ]
    }

    offers = render(declared_services=[engine], docker_containers=containers)

    assert offers == {
        "svc_abc123_web_8080": {
            "kind": "port",
            "title": "web",
            "host": "192.168.100.7",
            "port": 8080,
        },
        "svc_abc123_web_8443": {
            "kind": "port",
            "title": "web",
            "host": "192.168.100.7",
            "port": 8443,
        },
    }


def test_a_container_without_published_ports_offers_nothing():
    engine = declared("docker_engine", port=2375)
    containers = {
        "abc123": [
            DockerContainer(
                id="c1", name="db", image="postgres", state="running", is_running=True
            )
        ]
    }

    assert render(declared_services=[engine], docker_containers=containers) == {}


def test_podman_containers_offer_ports_at_the_hub_address():
    containers = {
        "hub_podman": [
            DockerContainer(
                id="web",
                name="web",
                image="nginx",
                state="running",
                is_running=True,
                host_ports=[8080],
            )
        ]
    }

    offers = render(docker_containers=containers)

    assert offers == {
        "hub_podman_web_8080": {
            "kind": "port",
            "title": "web",
            "host": "192.168.100.1",
            "port": 8080,
        }
    }


def test_containers_of_a_source_no_longer_declared_are_dropped():
    containers = {
        "gone": [
            DockerContainer(
                id="c1",
                name="web",
                image="nginx",
                state="running",
                is_running=True,
                host_ports=[8080],
            )
        ]
    }

    assert render(docker_containers=containers) == {}


def test_the_ai_offer_appears_only_while_the_gateway_serves():
    absent = render(is_ai_served=False)
    present = render(is_ai_served=True)

    assert absent == {}
    offer = present["ai"]
    assert offer["kind"] == "ai"
    assert offer["title"] == "AI tools"
    assert offer["description"]
    switcher = offer["platforms"]["linux-amd64"]["switcher"]
    assert switcher["github_repo"] == "SaladDay/cc-switch-cli"
    assert switcher["package_kind"] == "tar_binary"
    assert switcher["binary"] == "cc-switch"


def test_every_kind_together_keeps_distinct_ids():
    samba = declared("samba", id="s1", shares=[DeclaredShare(name="media")])
    http = declared("http", id="h1", port=8080, scheme="http", path="/")
    tcp = declared("generic_tcp", id="t1", port=5432)
    engine = declared("docker_engine", id="d1", port=2375)
    containers = {
        "d1": [
            DockerContainer(
                id="c1",
                name="web",
                image="nginx",
                state="running",
                is_running=True,
                host_ports=[8080],
            )
        ]
    }

    offers = render(
        hub_share_names=["media"],
        declared_services=[samba, http, tcp, engine],
        is_gitea_installed=True,
        gitea_url="http://192.168.100.1:3000/",
        docker_containers=containers,
        is_ai_served=True,
    )

    assert sorted(offers) == [
        "ai",
        "hub_gitea",
        "hub_share_media",
        "svc_d1_web_8080",
        "svc_h1",
        "svc_s1_media",
        "svc_t1",
    ]

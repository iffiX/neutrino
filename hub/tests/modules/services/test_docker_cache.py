"""The container cache: one batch of connections, shared and short-lived."""

import httpx
import pytest

from neutrino_hub.modules.services import docker as docker_module
from neutrino_hub.modules.services.config import DeclaredService
from neutrino_hub.modules.services.docker import (
    DockerContainerCache,
    DockerContainerController,
    DockerEngineError,
)

ENGINE = DeclaredService(
    id="d1",
    name="buildbox",
    kind="docker_engine",
    host="192.168.100.7",
    port=2375,
    created_at="2026-01-01T00:00:00+00:00",
)

ROWS = [
    {
        "Id": "c1",
        "Names": ["/web"],
        "Image": "nginx",
        "State": "running",
        "Ports": [
            {"PrivatePort": 80, "PublicPort": 8080, "Type": "tcp"},
            {"PrivatePort": 443, "Type": "tcp"},
        ],
    },
    {
        "Id": "c2",
        "Names": ["/db"],
        "Image": "postgres",
        "State": "exited",
        "Ports": [],
    },
]


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    @property
    def is_success(self):
        return 200 <= self.status_code < 300

    def json(self):
        return self._payload


@pytest.fixture()
def no_podman(monkeypatch, tmp_path):
    monkeypatch.setattr(docker_module, "PODMAN_BINARY", str(tmp_path / "no-podman"))


def test_the_engine_rows_are_parsed(monkeypatch, no_podman):
    monkeypatch.setattr(httpx, "get", lambda url, **kwargs: FakeResponse(ROWS))
    cache = DockerContainerCache()

    batch = cache.results([ENGINE])

    web, db = batch["d1"]
    assert (web.id, web.name, web.image) == ("c1", "web", "nginx")
    assert web.is_running and web.state == "running"
    # Only published ports count; the unpublished 443 is not one.
    assert web.host_ports == [8080]
    assert not db.is_running
    assert db.host_ports == []


def test_an_unreachable_engine_reads_as_empty(monkeypatch, no_podman):
    def refuse(url, **kwargs):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(httpx, "get", refuse)

    assert DockerContainerCache().results([ENGINE]) == {"d1": []}


def test_the_batch_is_cached_between_calls(monkeypatch, no_podman):
    calls = []

    def counted(url, **kwargs):
        calls.append(url)
        return FakeResponse(ROWS)

    monkeypatch.setattr(httpx, "get", counted)
    cache = DockerContainerCache()

    cache.results([ENGINE])
    cache.results([ENGINE])

    assert len(calls) == 1


def test_the_generation_moves_only_when_the_containers_change(monkeypatch, no_podman):
    payloads = [ROWS, ROWS, [ROWS[0]]]
    monkeypatch.setattr(
        httpx, "get", lambda url, **kwargs: FakeResponse(payloads.pop(0))
    )
    cache = DockerContainerCache()

    cache.refresh([ENGINE])
    first = cache.generation
    cache.refresh([ENGINE])
    unchanged = cache.generation
    cache.refresh([ENGINE])
    changed = cache.generation

    assert first == unchanged
    assert changed == first + 1


def test_refresh_one_replaces_only_that_engine(monkeypatch, no_podman):
    monkeypatch.setattr(httpx, "get", lambda url, **kwargs: FakeResponse(ROWS))
    cache = DockerContainerCache()
    cache.refresh([ENGINE])
    monkeypatch.setattr(httpx, "get", lambda url, **kwargs: FakeResponse([ROWS[0]]))

    fresh = cache.refresh_one(ENGINE)

    assert [container.name for container in fresh] == ["web"]
    assert [c.name for c in cache.results([ENGINE])["d1"]] == ["web"]


def test_podman_joins_the_batch_when_installed(monkeypatch, tmp_path):
    binary = tmp_path / "podman"
    binary.write_text("")
    monkeypatch.setattr(docker_module, "PODMAN_BINARY", str(binary))
    monkeypatch.setattr(httpx, "get", lambda url, **kwargs: FakeResponse(ROWS))

    class StubReader:
        def survey(self, *, declared_names):
            from neutrino_hub.modules.podman.ops import PodmanContainerState

            return [
                PodmanContainerState(
                    name="gitea",
                    image="gitea/gitea",
                    status="Up 2 hours",
                    is_running=True,
                    is_declared=False,
                    host_ports=[3000],
                )
            ]

    monkeypatch.setattr(docker_module, "PodmanStatusReader", StubReader)

    batch = DockerContainerCache().results([ENGINE])

    assert set(batch) == {"d1", "hub_podman"}
    podman = batch["hub_podman"][0]
    assert podman.name == "gitea"
    assert podman.host_ports == [3000]


def test_start_accepts_the_daemon_saying_done_or_already_there(monkeypatch):
    for status_code in (204, 304):
        monkeypatch.setattr(
            httpx, "post", lambda url, **kwargs: FakeResponse(None, status_code)
        )
        DockerContainerController().control(ENGINE, "c1", "start")


def test_a_refusal_carries_the_status(monkeypatch):
    monkeypatch.setattr(httpx, "post", lambda url, **kwargs: FakeResponse(None, 404))

    with pytest.raises(DockerEngineError) as caught:
        DockerContainerController().control(ENGINE, "gone", "stop")

    assert caught.value.code == "docker_action_refused"
    assert caught.value.params == {"action": "stop", "status": 404}


def test_a_silent_daemon_is_unreachable(monkeypatch):
    def refuse(url, **kwargs):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(httpx, "post", refuse)

    with pytest.raises(DockerEngineError) as caught:
        DockerContainerController().control(ENGINE, "c1", "start")

    assert caught.value.code == "docker_engine_unreachable"
    assert caught.value.params == {"host": "192.168.100.7"}

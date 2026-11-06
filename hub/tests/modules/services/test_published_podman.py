"""Containers' containers as the published list reads them from a device.

What these pin: each container is listed by its own state in the last
report, whatever state Containers reads, while the hub asks Containers to
run or to stop; a hub that asks nothing lists none.
"""

import pytest

from neutrino_hub.modules.services.published import PublishedServiceCache

DEVICE = "d1d1d1d1d1d1d1d1"
PLATFORM = {"os": "linux", "arch": "amd64"}
DETAILS = {
    "containers": [
        {
            "name": "whoami",
            "image": "docker.io/traefik/whoami:latest",
            "is_running": True,
            "host_bindings": [
                {"address": "", "port": 8088, "protocol": "tcp", "detected": "http"}
            ],
        },
        {
            "name": "ghost",
            "image": "",
            "is_running": False,
            "host_bindings": [],
            "code": "image_pull_failed",
            "params": {"name": "ghost", "image": "docker.io/library/none:9"},
        },
    ]
}


class FakeDesiredStates:
    """Containers' file and its want on one device."""

    def __init__(self, want: str):
        self._want = want

    def want_of(self, key: str, module: str) -> str:
        return self._want

    def read(self, key: str, module: str) -> dict:
        return {
            "containers": [
                {"name": "whoami", "services": []},
                {"name": "ghost", "services": []},
            ]
        }


def hosted(state: str, want: str = "running") -> "dict | None":
    cache = PublishedServiceCache(
        declared_probe=None,
        served_models=None,
        units=None,
        desired_states=FakeDesiredStates(want),
    )
    status = {"state": state, "details": DETAILS}
    return cache._hosted(DEVICE, "podman", status, PLATFORM)


@pytest.mark.parametrize("state", ["running", "stopped", "failed", "installing"])
def test_each_container_is_listed_by_its_own_state_whatever_containers_reads(state):
    """In the lab a running whoami left the Services page while a declared
    container whose image did not exist failed Containers."""
    podman = hosted(state)

    by_name = {container["name"]: container for container in podman["containers"]}
    assert by_name["whoami"]["is_running"] is True
    assert by_name["whoami"]["bindings"] == [(8088, "tcp", "http")]
    assert by_name["ghost"]["is_running"] is False


def test_a_hub_that_asks_containers_for_nothing_lists_none():
    assert hosted("running", want="") is None

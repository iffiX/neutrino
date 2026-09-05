"""The module half of the wire, in both directions.

What goes up is what is true and what the last order produced; what comes
down is what to do now. The generation is what stops an old agent from being
handed a shape it cannot read, so it is pinned here beside the shapes.
"""

import json

from neutrino_agent.constants import (
    AGENT_HEARTBEAT_PATH,
    AGENT_MODULE_PACKAGE_PATH,
    AGENT_WIRE_GENERATION,
)
from tests.core.test_loop import scripted_agent

ORDER = {
    "id": "order-1",
    "module": "openssh_server",
    "action": "enable",
    "artifact_key": "",
    "digest": "",
    "package_kind": "",
}

CATALOG = {
    "modules": {
        "openssh_server": {
            "title": "OpenSSH server",
            "description": "",
            "kind": "openssh",
            "is_builtin": True,
            "platform_key": "linux-debian",
            "entry": {"service": "ssh"},
            "verify": "",
            "package": "openssh_server",
        }
    },
    "services": [],
}


def test_the_wire_generation_is_the_one_this_build_speaks(config_path):
    agent = scripted_agent(config_path, [{"module_orders": [], "catalog_hash": ""}])

    agent.run_once()

    _, payload = agent._channel.posts[0]
    assert payload["wire"] == AGENT_WIRE_GENERATION
    # Bumped by this change: the reply's module half is orders now, and an
    # agent built to the old shape must reinstall rather than misread it.
    assert AGENT_WIRE_GENERATION == 3


def test_an_order_comes_down_and_its_result_goes_up(config_path):
    agent = scripted_agent(
        config_path,
        [
            {"module_orders": [ORDER], "catalog": CATALOG, "catalog_hash": "h1"},
            {"module_orders": [ORDER], "catalog_hash": "h1"},
        ],
    )

    agent.run_once()
    agent._engine._reconcile()
    agent.run_once()

    _, second = agent._channel.posts[1]
    results = second["module_results"]
    assert [result["id"] for result in results] == ["order-1"]
    assert results[0]["module"] == "openssh_server"
    assert results[0]["state"] in ("done", "failed")


def test_a_result_stops_riding_up_once_the_hub_stops_asking(config_path):
    agent = scripted_agent(
        config_path,
        [
            {"module_orders": [ORDER], "catalog": CATALOG, "catalog_hash": "h1"},
            {"module_orders": [], "catalog_hash": "h1"},
            {"module_orders": [], "catalog_hash": "h1"},
        ],
    )

    agent.run_once()
    agent._engine._reconcile()
    agent.run_once()
    agent.run_once()

    _, third = agent._channel.posts[2]
    assert third["module_results"] == []


def test_the_machine_reports_state_without_being_ordered_to(config_path):
    agent = scripted_agent(
        config_path,
        [
            {"module_orders": [], "catalog": CATALOG, "catalog_hash": "h1"},
            {"module_orders": [], "catalog_hash": "h1"},
        ],
    )

    agent.run_once()
    agent._engine._reconcile()
    agent.run_once()

    _, second = agent._channel.posts[1]
    # A module nobody has ordered anything about is still reported, and
    # still untouched: "not asked for" is not "take it off this machine".
    assert "openssh_server" in second["modules"]


def test_the_bytes_are_asked_for_on_their_own_endpoint(config_path):
    agent = scripted_agent(config_path, [{"module_orders": [], "catalog_hash": ""}])
    agent.run_once()
    asked: list = []

    def fake_download(path, payload, destination):
        asked.append((path, dict(payload)))
        with open(destination, "wb") as stream:
            stream.write(b"!<arch>bytes")
        return ""

    agent._channel.post_download = fake_download

    refusal = agent._fetch_artifact("todesk-linux-debian-amd64-abcd", "/dev/null")

    assert refusal == {}
    # A beat stays a beat: the order names a key, and the bytes come over
    # the download endpoint the self-update already uses the shape of.
    assert asked[0][0] == AGENT_MODULE_PACKAGE_PATH
    assert asked[0][1] == {"artifact_key": "todesk-linux-debian-amd64-abcd"}


def test_bytes_that_do_not_match_the_hubs_digest_are_refused(config_path, tmp_path):
    agent = scripted_agent(config_path, [{"module_orders": [], "catalog_hash": ""}])
    agent.run_once()
    landed = tmp_path / "package.deb"

    def fake_download(path, payload, destination):
        with open(destination, "wb") as stream:
            stream.write(b"something else")
        return "0" * 64

    agent._channel.post_download = fake_download

    refusal = agent._fetch_artifact("key", str(landed))

    assert refusal == {"code": "module_digest_mismatch", "params": {}}


def test_a_local_toggle_asks_the_hub_and_applies_nothing(config_path):
    agent = scripted_agent(
        config_path,
        [
            {"module_orders": [], "catalog": CATALOG, "catalog_hash": "h1"},
            {"module_orders": [], "catalog_hash": "h1"},
        ],
    )
    agent.run_once()

    agent.request_module("openssh_server", is_enabled=True)
    agent.run_once()

    _, second = agent._channel.posts[1]
    # The machine's own page asks; it never acts. The hub answers with an
    # order, which is the same door the panel's button goes through.
    assert second["module_requests"] == {"openssh_server": {"is_enabled": True}}
    assert json.dumps(second["module_results"]) == "[]"

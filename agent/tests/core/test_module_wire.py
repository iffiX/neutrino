"""The module half of the wire, in both directions.

What comes down is one order stream carrying the module resolved for this
platform; what goes up is each line as it happens and the close that says
how it went, plus the module's state on every report. The generation is
what stops an old agent from being handed a shape it cannot read, so it is
pinned here beside the shapes.
"""

from neutrino_agent.constants import AGENT_MODULE_PACKAGE_PATH, AGENT_WIRE_GENERATION
from tests.core.test_loop import WELCOME, scripted_agent
from tests.core.test_session import ScriptedClient

ORDER = {
    "id": "order-1",
    "module": "fakedesk",
    "action": "install",
    "artifact_key": "fakedesk-linux-debian-amd64-abcd",
    "digest": "",
    "package_kind": "deb",
    "resolved": {
        "title": "FakeDesk",
        "description": "",
        "kind": "package",
        "installer": "hub",
        "platform_key": "linux-debian-amd64",
        "entry": {"package_kind": "deb"},
        "verify": "",
        "package": "fakedesk",
    },
}


def test_the_wire_generation_is_the_one_this_build_speaks():
    # Bumped by this change: the desired state carries the catalog and each
    # module's configuration, a validate stream joins the socket, and an
    # agent built to the old shape must reinstall rather than misread it.
    assert AGENT_WIRE_GENERATION == 6


def test_an_order_stream_runs_the_engine_and_closes_with_its_result(
    config_path, monkeypatch
):
    agent, _ = scripted_agent(config_path, monkeypatch)
    lines: list = []
    monkeypatch.setattr(
        agent._engine,
        "_carry_out",
        lambda action, name, resolved, order: {"code": "install_unconfirmed"},
    )
    client = ScriptedClient()
    client.feed(WELCOME)
    session = agent._open_session()
    session._client = client
    session.connect()
    client.feed({"type": "open", "stream": "00000001", "kind": "order", "args": ORDER})

    (closed,) = client.wait_for("close")

    assert closed["state"] == "failed"
    assert closed["code"] == "install_unconfirmed"
    assert "fakedesk: install" in closed["output"]
    assert [event["line"] for event in client.frames("event")] == ["fakedesk: install"]
    # The module the order carried is reported from then on.
    assert "fakedesk" in agent.catalog()["modules"]
    session.close()
    del lines


def test_the_bytes_are_asked_for_on_their_own_endpoint(config_path, monkeypatch):
    agent, _ = scripted_agent(config_path, monkeypatch)
    asked: list = []

    def fake_download(path, payload, destination):
        asked.append((path, dict(payload)))
        with open(destination, "wb") as stream:
            stream.write(b"!<arch>bytes")
        return ""

    agent._channel.post_download = fake_download

    refusal = agent._fetch_artifact("fakedesk-linux-debian-amd64-abcd", "/dev/null")

    assert refusal == {}
    # The order names a key, and the bytes come over the download endpoint
    # the self-update already uses the shape of.
    assert asked[0][0] == AGENT_MODULE_PACKAGE_PATH
    assert asked[0][1] == {"artifact_key": "fakedesk-linux-debian-amd64-abcd"}


def test_bytes_that_do_not_match_the_hubs_digest_are_refused(
    config_path, monkeypatch, tmp_path
):
    agent, _ = scripted_agent(config_path, monkeypatch)
    landed = tmp_path / "package.deb"

    def fake_download(path, payload, destination):
        with open(destination, "wb") as stream:
            stream.write(b"something else")
        return "0" * 64

    agent._channel.post_download = fake_download

    refusal = agent._fetch_artifact("key", str(landed))

    assert refusal == {"code": "module_digest_mismatch", "params": {}}

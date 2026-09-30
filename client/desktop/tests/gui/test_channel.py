"""The in-process channel: the route table, with no transport between."""

from neutrino_client.gui.bridge import GuiBridge
from neutrino_client.gui.channel import InProcessChannel
from tests.conftest import FakeResident


def test_a_request_is_the_route_tables_own_answer():
    resident = FakeResident()
    channel = InProcessChannel(resident=resident)

    status, state = channel.request(method="GET", path="/api/state")
    posted, reply = channel.request(
        method="POST", path="/api/services/port", body={"id": "svc_tcp"}
    )

    assert status == 200 and state["hostname"] == "box"
    assert posted == 200
    assert resident.service_calls == [("port", {"id": "svc_tcp"})]
    assert "forwards" in reply


def test_the_bridge_rides_the_channel_end_to_end():
    resident = FakeResident()
    bridge = GuiBridge(channel=InProcessChannel(resident=resident))

    reply = bridge.handle(
        {"id": 3, "method": "POST", "path": "/api/show", "body": None}
    )

    assert reply == {"id": 3, "status": 200, "body": {}}
    assert resident.shows == 1


def test_an_unknown_route_answers_typed_not_closed():
    channel = InProcessChannel(resident=FakeResident())

    status, reply = channel.request(method="GET", path="/api/nothing")

    assert (status, reply["code"]) == (404, "unknown_request")

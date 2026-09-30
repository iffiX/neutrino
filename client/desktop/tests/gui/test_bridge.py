"""The bridge: exactly three request fields cross.

The page hands the shell ``{id, method, path, body}``; the bridge forwards
method, path and body over the channel and nothing else.
"""

from neutrino_client.gui.bridge import GuiBridge, GuiWindowApi


class FakeGuiChannel:
    """A channel that records each request and answers a canned reply."""

    def __init__(self, *, status=200, reply=None, error=None):
        self.status = status
        self.reply = reply if reply is not None else {"hostname": "box"}
        self.error = error
        self.asked = []

    def request(self, *, method, path, body=None):
        self.asked.append((method, path, body))
        if self.error is not None:
            raise self.error
        return self.status, dict(self.reply)


def test_a_get_round_trips_with_its_id():
    channel = FakeGuiChannel()
    bridge = GuiBridge(channel=channel)

    reply = bridge.handle(
        {"id": 7, "method": "GET", "path": "/api/state", "body": None}
    )

    assert reply == {"id": 7, "status": 200, "body": {"hostname": "box"}}
    assert channel.asked == [("GET", "/api/state", None)]


def test_a_post_carries_its_body_and_nothing_else():
    channel = FakeGuiChannel()
    bridge = GuiBridge(channel=channel)

    bridge.handle(
        {
            "id": 8,
            "method": "POST",
            "path": "/api/services/port",
            "body": {"id": "svc_tcp", "is_enabled": True},
            "account": "root",
            "token": "forged",
        }
    )

    assert channel.asked == [
        ("POST", "/api/services/port", {"id": "svc_tcp", "is_enabled": True})
    ]


def test_a_get_never_carries_a_body():
    channel = FakeGuiChannel()
    bridge = GuiBridge(channel=channel)

    bridge.handle(
        {"id": 1, "method": "GET", "path": "/api/state", "body": {"smuggled": True}}
    )

    assert channel.asked == [("GET", "/api/state", None)]


def test_a_shapeless_post_body_rides_as_an_empty_object():
    channel = FakeGuiChannel()
    bridge = GuiBridge(channel=channel)

    bridge.handle({"id": 2, "method": "POST", "path": "/api/disconnect", "body": "x"})

    assert channel.asked == [("POST", "/api/disconnect", {})]


def test_an_unknown_method_reads_as_a_get():
    channel = FakeGuiChannel()
    bridge = GuiBridge(channel=channel)

    bridge.handle({"id": 3, "method": "DELETE", "path": "/api/state", "body": None})

    assert channel.asked == [("GET", "/api/state", None)]


def test_a_dead_channel_answers_the_typed_code():
    channel = FakeGuiChannel(error=OSError("gone"))
    bridge = GuiBridge(channel=channel)

    reply = bridge.handle(
        {"id": 4, "method": "GET", "path": "/api/state", "body": None}
    )

    assert reply == {
        "id": 4,
        "status": 0,
        "body": {"code": "control_channel_closed", "params": {}},
    }


def test_a_shapeless_message_asks_for_nothing_but_still_answers():
    channel = FakeGuiChannel(status=404, reply={"code": "unknown_request"})
    bridge = GuiBridge(channel=channel)

    reply = bridge.handle("not an object")

    assert channel.asked == [("GET", "", None)]
    assert reply["id"] is None
    assert reply["status"] == 404


def test_the_window_api_is_the_bridge_behind_one_method():
    channel = FakeGuiChannel()
    api = GuiWindowApi(GuiBridge(channel=channel))

    reply = api.request({"id": 5, "method": "GET", "path": "/api/state", "body": None})

    assert reply["id"] == 5
    assert channel.asked == [("GET", "/api/state", None)]

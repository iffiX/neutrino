"""The route table, driven directly: one table for both transports."""

import json

from neutrino_client.control import routes
from neutrino_client.core.enrollment import EnrollmentError
from tests.conftest import FakeSession


def test_state_carries_the_persons_facts_and_no_token():
    session = FakeSession()

    status, state = routes.dispatch("GET", "/api/state", None, session)

    assert status == 200
    assert state["hostname"] == "box"
    assert state["is_connected"] is True
    assert state["gateway_url"] == "https://hub.lan:8443"
    assert state["hub_version"] == "0.2.0"
    assert state["home"] == "/home/alice"
    assert [entry["type"] for entry in state["services"]] == [
        "ai",
        "web",
        "port",
        "file",
        "rdp",
    ]
    assert state["forwards"]["svc_tcp"]["local_port"] == 5432
    assert state["mounts"][0]["record_id"] == "r1"
    assert state["ai"]["is_enabled"] is True
    assert "tok" not in json.dumps(state)
    assert "caller" not in state and "accounts" not in state and "modules" not in state


def test_connect_and_disconnect_ride_the_session():
    session = FakeSession()

    status, state = routes.dispatch(
        "POST", "/api/connect", {"link": "neutrino://enroll/x"}, session
    )
    assert status == 200
    assert session.connected_links == ["neutrino://enroll/x"]
    assert "error" not in state

    status, state = routes.dispatch("POST", "/api/disconnect", {}, session)
    assert status == 200
    assert session.is_disconnected is True
    assert state["is_connected"] is False


def test_a_refused_link_reports_typed_on_the_state():
    session = FakeSession()
    session.connect_error = EnrollmentError("link_not_for_client", {"kind": "device"})

    status, state = routes.dispatch("POST", "/api/connect", {"link": "x"}, session)

    assert status == 200
    assert state["error"] == {
        "code": "link_not_for_client",
        "params": {"kind": "device"},
    }


def test_service_actions_carry_only_the_body():
    session = FakeSession()

    status, state = routes.dispatch(
        "POST",
        "/api/services/port",
        {"id": "svc_tcp", "is_enabled": True, "account": "root"},
        session,
    )

    assert status == 200
    assert session.service_calls == [
        ("port", {"id": "svc_tcp", "is_enabled": True, "account": "root"})
    ]
    assert "forwards" in state


def test_a_service_refusal_maps_to_its_status():
    session = FakeSession()
    for code, status in (
        ("unknown_request", 404),
        ("fs_refused", 403),
        ("client_disabled", 403),
        ("mountpoint_not_empty", 400),
    ):
        session.service_reply = {"code": code, "params": {}}
        answered, reply = routes.dispatch("POST", "/api/services/file", {}, session)
        assert (answered, reply["code"]) == (status, code)


def test_the_directory_listing_runs_as_the_person():
    session = FakeSession()

    status, reply = routes.dispatch("GET", "/api/fs?path=/srv", None, session)
    assert status == 200
    assert reply == {"path": "/srv", "dirs": ["docs", "media"]}
    assert session.platform.fs_calls[-1] == ("list", "/srv")

    status, reply = routes.dispatch("GET", "/api/fs", None, session)
    assert reply["path"] == "/home/alice"

    session.platform.fs_error = OSError("refused")
    status, reply = routes.dispatch("GET", "/api/fs?path=/srv", None, session)
    assert (status, reply["code"]) == (403, "fs_refused")


def test_making_a_folder_wants_an_absolute_path(tmp_path):
    session = FakeSession()

    status, reply = routes.dispatch(
        "POST", "/api/fs", {"path": str(tmp_path / "new")}, session
    )
    assert status == 200
    assert session.platform.fs_calls[-1] == ("mkdir", str(tmp_path / "new"))

    status, reply = routes.dispatch("POST", "/api/fs", {"path": "relative"}, session)
    assert (status, reply["code"]) == (403, "fs_refused")

    status, reply = routes.dispatch(
        "POST", "/api/fs", {"path": "C:\\Users\\a"}, session
    )
    assert status == 200


def test_show_reaches_the_session():
    session = FakeSession()

    status, reply = routes.dispatch("POST", "/api/show", {}, session)

    assert (status, reply) == (200, {})
    assert session.shows == 1


def test_unknown_routes_and_methods_answer_a_code():
    session = FakeSession()

    for method, path in (
        ("GET", "/api/nothing"),
        ("POST", "/api/nothing"),
        ("GET", "/"),
    ):
        status, reply = routes.dispatch(method, path, {}, session)
        assert (status, reply["code"]) == (404, "unknown_request")
    status, reply = routes.dispatch("DELETE", "/api/state", None, session)
    assert (status, reply["code"]) == (404, "unknown_request")


def test_a_shapeless_body_acts_as_an_empty_one():
    session = FakeSession()

    status, _state = routes.dispatch("POST", "/api/services/ai", "garbage", session)

    assert status == 200
    assert session.service_calls == [("ai", {})]

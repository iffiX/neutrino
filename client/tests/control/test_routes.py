"""The route table, driven directly: one table for both transports."""

import json
import time

import pytest

from neutrino_client.control import routes
from neutrino_client.exceptions import EnrollmentError
from tests.conftest import FakeResident


def test_state_carries_the_persons_facts_the_hubs_and_no_token():
    resident = FakeResident()

    status, state = routes.dispatch("GET", "/api/state", None, resident)

    assert status == 200
    assert state["hostname"] == "box"
    assert state["is_connected"] is True
    assert state["exit_hub_id"] == "h1"
    assert state["home"] == "/home/alice"
    assert [(hub["hub_id"], hub["is_exit"]) for hub in state["hubs"]] == [
        ("h1", True),
        ("h2", False),
    ]
    assert set(state["hubs"][0]) == {
        "hub_id",
        "hub_name",
        "hub_software",
        "binding_id",
        "name",
        "gateway_url",
        "connection_state",
        "is_disabled",
        "is_exit",
        "last_error",
    }
    assert [(entry["hub_id"], entry["type"]) for entry in state["services"]] == [
        ("h1", "ai"),
        ("h1", "web"),
        ("h1", "port"),
        ("h1", "file"),
        ("h1", "rdp"),
        ("h2", "ai"),
        ("h2", "web"),
        ("h2", "port"),
        ("h2", "file"),
        ("h2", "rdp"),
    ]
    assert state["forwards"]["h1/svc_tcp"]["local_port"] == 5432
    assert state["mounts"][0]["record_id"] == "r1"
    assert state["mounts"][0]["hub_id"] == "h1"
    assert state["ai"]["is_enabled"] is True
    assert "tok" not in json.dumps(state)
    for gone in ("connection_state", "gateway_url", "hub_version", "last_error"):
        assert gone not in state
    assert "caller" not in state and "accounts" not in state and "modules" not in state


def test_an_unbound_resident_states_no_hub_and_no_service():
    resident = FakeResident()
    resident.is_bound = False

    _status, state = routes.dispatch("GET", "/api/state", None, resident)

    assert state["is_connected"] is False
    assert state["hubs"] == [] and state["services"] == []
    assert state["exit_hub_id"] == ""


def test_join_and_leave_ride_the_resident():
    resident = FakeResident()

    status, state = routes.dispatch(
        "POST", "/api/join", {"link": "neutrino://enroll/x"}, resident
    )
    assert status == 200
    assert resident.connected_links == ["neutrino://enroll/x"]
    assert "error" not in state

    status, state = routes.dispatch("POST", "/api/leave", {"hub_id": "h2"}, resident)
    assert status == 200
    assert resident.disconnected == ["h2"]
    assert [hub["hub_id"] for hub in state["hubs"]] == ["h1"]

    status, state = routes.dispatch("POST", "/api/leave", {}, resident)
    assert status == 200
    assert resident.disconnected == ["h2", "h1"]
    assert state["is_connected"] is False


def test_leaving_a_hub_nobody_joined_is_typed():
    resident = FakeResident()

    status, reply = routes.dispatch("POST", "/api/leave", {"hub_id": "h9"}, resident)
    assert (status, reply) == (404, {"code": "unknown_hub", "params": {"hub_id": "h9"}})

    status, reply = routes.dispatch("POST", "/api/leave", {}, resident)
    assert (status, reply["code"]) == (404, "unknown_hub")
    assert resident.disconnected == []


def test_choosing_the_exit_answers_the_state_with_the_choice():
    resident = FakeResident()

    status, state = routes.dispatch("POST", "/api/exit/set", {"hub_id": "h2"}, resident)

    assert status == 200
    assert resident.exits == ["h2"]
    assert state["exit_hub_id"] == "h2"
    assert [hub["is_exit"] for hub in state["hubs"]] == [False, True]


def test_only_a_connected_hub_can_be_the_exit():
    resident = FakeResident()
    resident.hubs_value[1]["connection_state"] = "reconnecting"

    status, reply = routes.dispatch("POST", "/api/exit/set", {"hub_id": "h2"}, resident)
    assert (status, reply) == (400, {"code": "no_exit_hub", "params": {"hub_id": "h2"}})

    status, reply = routes.dispatch("POST", "/api/exit/set", {"hub_id": "h9"}, resident)
    assert (status, reply) == (404, {"code": "unknown_hub", "params": {"hub_id": "h9"}})
    assert resident.exits == []


def test_a_refused_link_reports_typed_on_the_state():
    resident = FakeResident()
    resident.connect_error = EnrollmentError("link_not_for_client", {"kind": "device"})

    status, state = routes.dispatch("POST", "/api/join", {"link": "x"}, resident)

    assert status == 200
    assert state["error"] == {
        "code": "link_not_for_client",
        "params": {"kind": "device"},
    }


def test_service_actions_carry_only_the_body():
    resident = FakeResident()

    status, state = routes.dispatch(
        "POST",
        "/api/services/port",
        {"hub_id": "h2", "id": "svc_tcp", "is_enabled": True, "account": "root"},
        resident,
    )

    assert status == 200
    assert resident.service_calls == [
        (
            "port",
            {"hub_id": "h2", "id": "svc_tcp", "is_enabled": True, "account": "root"},
        )
    ]
    assert "forwards" in state


def test_starting_the_session_takes_a_replaced_binding_back():
    resident = FakeResident()
    resident.hubs_value[0]["connection_state"] = "replaced"

    status, state = routes.dispatch(
        "POST", "/api/session/start", {"hub_id": "h1"}, resident
    )

    assert status == 200
    assert resident.reconnects == ["h1"]
    assert state["hubs"][0]["connection_state"] == "reconnecting"


def test_starting_the_session_names_the_hub_or_the_one_joined():
    resident = FakeResident()

    status, reply = routes.dispatch(
        "POST", "/api/session/start", {"hub_id": "h9"}, resident
    )
    assert (status, reply) == (
        404,
        {"code": "unknown_hub", "params": {"hub_id": "h9"}},
    )

    status, _reply = routes.dispatch("POST", "/api/session/start", {}, resident)
    assert status == 404
    resident.hubs_value.pop()
    status, _reply = routes.dispatch("POST", "/api/session/start", {}, resident)
    assert status == 200
    assert resident.reconnects == [""]


def test_a_service_refusal_maps_to_its_status():
    resident = FakeResident()
    for code, status in (
        ("unknown_request", 404),
        ("unknown_hub", 404),
        ("fs_refused", 403),
        ("client_disabled", 403),
        ("mountpoint_not_empty", 400),
        ("mountpoint_in_use", 400),
        ("no_exit_hub", 400),
    ):
        resident.service_reply = {"code": code, "params": {}}
        answered, reply = routes.dispatch("POST", "/api/services/file", {}, resident)
        assert (answered, reply["code"]) == (status, code)


def test_the_directory_listing_runs_as_the_person():
    resident = FakeResident()

    status, reply = routes.dispatch("GET", "/api/fs?path=/srv", None, resident)
    assert status == 200
    assert reply == {"path": "/srv", "dirs": ["docs", "media"]}
    assert resident.platform.fs_calls[-1] == ("list", "/srv")

    status, reply = routes.dispatch("GET", "/api/fs", None, resident)
    assert reply["path"] == "/home/alice"

    resident.platform.fs_error = OSError("refused")
    status, reply = routes.dispatch("GET", "/api/fs?path=/srv", None, resident)
    assert (status, reply["code"]) == (403, "fs_refused")


def test_making_a_folder_wants_an_absolute_path(tmp_path):
    resident = FakeResident()

    status, reply = routes.dispatch(
        "POST", "/api/fs", {"path": str(tmp_path / "new")}, resident
    )
    assert status == 200
    assert resident.platform.fs_calls[-1] == ("mkdir", str(tmp_path / "new"))

    status, reply = routes.dispatch("POST", "/api/fs", {"path": "relative"}, resident)
    assert (status, reply["code"]) == (403, "fs_refused")

    status, reply = routes.dispatch(
        "POST", "/api/fs", {"path": "C:\\Users\\a"}, resident
    )
    assert status == 200


def test_refresh_reaches_the_resident_and_answers_the_state():
    resident = FakeResident()

    status, state = routes.dispatch("POST", "/api/refresh", {}, resident)

    assert status == 200
    assert resident.refreshes == 1
    assert [hub["hub_id"] for hub in state["hubs"]] == ["h1", "h2"]


def test_show_reaches_the_resident():
    resident = FakeResident()

    status, reply = routes.dispatch("POST", "/api/show", {}, resident)

    assert (status, reply) == (200, {})
    assert resident.shows == 1


@pytest.fixture
def quit_without_ending(monkeypatch):
    """The quit route with the process end recorded instead of taken."""
    ended = []
    monkeypatch.setattr(routes, "QUIT_ANSWER_GRACE_S", 0)
    monkeypatch.setattr(routes, "end_process", lambda: ended.append(1))
    return ended


def test_quit_answers_first_and_shuts_the_resident_down(quit_without_ending):
    resident = FakeResident()

    status, reply = routes.dispatch("POST", "/api/quit", {}, resident)

    assert (status, reply) == (200, {})
    assert resident.is_shut_down.wait(timeout=5)
    assert resident.shutdowns == 1
    for _ in range(100):
        if quit_without_ending:
            break
        time.sleep(0.01)
    assert quit_without_ending == [1]


def test_the_state_names_the_language_every_surface_words_itself_in():
    resident = FakeResident()
    resident.language_value = "zh-CN"

    _status, state = routes.dispatch("GET", "/api/state", None, resident)

    assert state["language"] == "zh-CN"


def test_picking_a_language_keeps_it_and_answers_the_new_state():
    resident = FakeResident()

    status, state = routes.dispatch(
        "POST", "/api/language", {"language": "zh-CN"}, resident
    )

    assert status == 200
    assert resident.language_value == "zh-CN"
    assert state["language"] == "zh-CN"


def test_the_state_names_the_theme_the_window_draws_itself_in():
    resident = FakeResident()
    resident.theme_value = "light"

    _status, state = routes.dispatch("GET", "/api/state", None, resident)

    assert state["theme"] == "light"


def test_picking_a_theme_keeps_it_and_answers_the_new_state():
    resident = FakeResident()

    status, state = routes.dispatch("POST", "/api/theme", {"theme": "light"}, resident)

    assert status == 200
    assert resident.theme_value == "light"
    assert state["theme"] == "light"


def test_unknown_routes_and_methods_answer_a_code():
    resident = FakeResident()

    for method, path in (
        ("GET", "/api/nothing"),
        ("POST", "/api/nothing"),
        ("GET", "/"),
    ):
        status, reply = routes.dispatch(method, path, {}, resident)
        assert (status, reply["code"]) == (404, "unknown_request")
    status, reply = routes.dispatch("DELETE", "/api/state", None, resident)
    assert (status, reply["code"]) == (404, "unknown_request")


def test_a_shapeless_body_acts_as_an_empty_one():
    resident = FakeResident()

    status, _state = routes.dispatch("POST", "/api/services/ai", "garbage", resident)

    assert status == 200
    assert resident.service_calls == [("ai", {})]

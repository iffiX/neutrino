"""The route table, driven directly: one table for both transports."""

import base64
import json
import time

import pytest

from neutrino_client import edition
from neutrino_client.control import page, routes
from neutrino_client.core.resident import ClientResident
from neutrino_client.exceptions import EnrollmentError
from neutrino_client.platforms.darwin import DarwinPlatform
from tests.conftest import FakeClientPlatform, FakeResident, discard


def test_the_state_on_a_mac_offers_a_volume_and_no_place():
    resident = ClientResident(log=discard, platform=DarwinPlatform())
    try:
        _status, state = routes.dispatch("GET", "/api/state", None, resident)
    finally:
        resident.shutdown()

    assert state["mount_location_shape"] == "volume"
    assert state["mount_location_suggestion"] == ""
    assert state["mount_location_choices"] == []


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
        "binding_id",
        "gateway_url",
        "software",
        "connection",
        "wait_reason",
        "wait_code",
        "next_round_at",
        "is_pending",
        "last_error",
        "is_exit",
        "overlay",
        "jobs",
    }
    assert set(state["hubs"][0]["overlay"]) == {
        "network",
        "networks",
        "state",
        "stage",
        "is_waiting",
        "address",
        "error",
    }
    assert state["hubs"][0]["jobs"] == {
        "is_refreshing": False,
        "overlay_job": "",
        "is_leaving": False,
    }
    assert all(
        entry["job"] == "" and entry["last_error"] is None
        for entry in state["services"]
    )
    assert state["notices"] == []
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
    assert state["services"][2]["forward"] == 5432
    assert state["mounts"][0]["record_id"] == "r1"
    assert state["mounts"][0]["hub_id"] == "h1"
    assert state["ai"]["is_enabled"] is True
    assert "tok" not in json.dumps(state)
    for gone in ("connection", "gateway_url", "hub_version", "last_error"):
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
    resident.hubs_value[1]["connection"] = "connecting"

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
    assert "services" in state


def test_a_local_port_setting_reaches_the_resident_and_answers_the_state():
    resident = FakeResident()

    status, state = routes.dispatch(
        "POST",
        "/api/forward/configure",
        {"hub_id": "h1", "id": "svc_tcp", "local_port": 15432},
        resident,
    )
    assert status == 200 and "services" in state
    resident.forward_reply = {"code": "port_taken", "params": {"port": 15432}}
    status, reply = routes.dispatch(
        "POST",
        "/api/forward/configure",
        {"hub_id": "h1", "id": "svc_web", "local_port": "auto"},
        resident,
    )

    assert (status, reply["code"]) == (400, "port_taken")
    assert resident.forward_settings == [
        ("h1", "svc_tcp", 15432),
        ("h1", "svc_web", "auto"),
    ]


def test_an_about_link_opens_in_the_browser_and_nothing_but_https_does():
    resident = FakeResident()

    status, reply = routes.dispatch(
        "POST", "/api/open_link", {"url": "https://github.com/iffiX/neutrino"}, resident
    )
    assert (status, reply) == (200, {})
    for url in ("file:///etc/passwd", "http://example.com", ""):
        status, reply = routes.dispatch(
            "POST", "/api/open_link", {"url": url}, resident
        )
        assert (status, reply["code"]) == (404, "unknown_request")

    assert resident.platform.opened_urls == ["https://github.com/iffiX/neutrino"]


def test_the_state_names_the_versions_the_package_carries():
    _status, state = routes.dispatch("GET", "/api/state", None, FakeResident())

    assert isinstance(state["carried_versions"], dict)
    assert state["edition"] == edition.EDITION


def test_starting_the_session_takes_a_replaced_binding_back():
    resident = FakeResident()
    resident.hubs_value[0]["connection"] = "replaced"

    status, state = routes.dispatch(
        "POST", "/api/session/start", {"hub_id": "h1"}, resident
    )

    assert status == 200
    assert resident.reconnects == ["h1"]
    assert state["hubs"][0]["connection"] == "connecting"


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


def test_closing_a_notice_drops_only_that_one_and_answers_the_state():
    resident = FakeResident()
    resident.notices_value = [
        {"id": "n1", "code": "binding_unknown", "params": {"hub": "home"}},
        {"id": "n2", "code": "binding_unknown", "params": {"hub": "office"}},
    ]

    status, state = routes.dispatch("POST", "/api/notice/close", {"id": "n1"}, resident)

    assert status == 200
    assert [notice["id"] for notice in state["notices"]] == ["n2"]


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


# --- the virtual network and the terminals ---


@pytest.mark.parametrize(
    "path, verb",
    [
        ("/api/overlay/connect", "connect"),
        ("/api/overlay/cancel", "cancel"),
        ("/api/overlay/disconnect", "disconnect"),
    ],
)
def test_a_network_step_reaches_the_resident_and_answers_the_state(path, verb):
    resident = FakeResident()

    status, state = routes.dispatch("POST", path, {"hub_id": "h1"}, resident)

    assert status == 200
    assert resident.overlay_calls == [(verb, "h1")]
    assert state["hubs"][0]["overlay"]["state"] == "on"


def test_a_pick_names_the_hub_and_the_provider():
    resident = FakeResident()

    status, state = routes.dispatch(
        "POST", "/api/overlay/pick", {"hub_id": "h1", "provider": "easytier"}, resident
    )

    assert status == 200
    assert resident.overlay_calls == [("pick", "h1", "easytier")]
    assert [
        network["provider"] for network in state["hubs"][0]["overlay"]["networks"]
    ] == [
        "netbird",
        "easytier",
    ]


def test_a_network_step_on_a_hub_nobody_joined_answers_unknown_hub():
    resident = FakeResident()
    resident.overlay_reply = {"code": "unknown_hub", "params": {"hub_id": "h9"}}

    status, reply = routes.dispatch(
        "POST", "/api/overlay/connect", {"hub_id": "h9"}, resident
    )

    assert status == 404
    assert reply == {"code": "unknown_hub", "params": {"hub_id": "h9"}}


def test_the_old_network_routes_are_gone():
    for path in ("/api/overlay/join", "/api/overlay/leave"):
        status, reply = routes.dispatch("POST", path, {"hub_id": "h1"}, FakeResident())
        assert (status, reply["code"]) == (404, "unknown_request")


def test_the_state_carries_the_terminals_and_sessions_of_every_hub():
    _status, state = routes.dispatch("GET", "/api/state", None, FakeResident())

    machines = state["terminals"]["machines"]
    assert [(row["hub_id"], row["device_id"]) for row in machines] == [
        ("h1", "d_lepton"),
        ("h1", "d_muon"),
    ]
    (session,) = state["terminals"]["sessions"]
    assert set(session) >= {
        "session_id",
        "device_id",
        "owner",
        "is_owned",
        "is_persistent",
        "is_shared",
        "attached_count",
        "title",
    }


# --- the clipboard ---


def test_a_copy_writes_the_text_to_the_clipboard_and_answers_empty():
    resident = FakeResident()

    status, reply = routes.dispatch(
        "POST", "/api/clipboard", {"text": "git status"}, resident
    )

    assert (status, reply) == (200, {})
    assert resident.clipboard_written == ["git status"]


def test_a_copy_the_platform_refuses_answers_its_code():
    resident = FakeResident()
    resident.clipboard_write_reply = {
        "code": "clipboard_unwritable",
        "params": {"detail": "no display"},
    }

    status, reply = routes.dispatch("POST", "/api/clipboard", {"text": "x"}, resident)

    assert status == 400
    assert reply["code"] == "clipboard_unwritable"


def test_a_paste_reads_the_clipboard():
    status, reply = routes.dispatch("GET", "/api/clipboard", None, FakeResident())

    assert (status, reply) == (200, {"text": "echo pasted\n"})


# --- the terminals ---


def test_attach_answers_101_naming_the_terminal_and_the_resident_gets_the_size():
    resident = FakeResident()

    status, reply = routes.dispatch(
        "POST",
        "/api/terminal/attach",
        {"hub_id": "h1", "device_id": "d_lepton", "cols": 120, "rows": 40},
        resident,
    )

    assert (status, reply) == (101, {"terminal_id": "t1"})
    assert resident.terminal_calls == [("open", "h1", "d_lepton", 120, 40)]


def test_a_shared_attach_says_so_to_the_resident():
    resident = FakeResident()

    routes.dispatch(
        "POST",
        "/api/terminal/attach",
        {"hub_id": "h1", "device_id": "d1", "cols": 80, "rows": 24, "is_shared": True},
        resident,
    )

    assert resident.terminal_calls == [("open", "h1", "d1", 80, 24, "shared")]


def test_exec_answers_101_and_the_resident_gets_the_command():
    resident = FakeResident()

    status, reply = routes.dispatch(
        "POST",
        "/api/terminal/exec",
        {
            "hub_id": "h1",
            "device_id": "d1",
            "argv": ["psql", "app"],
            "is_tty": False,
            "cols": 80,
            "rows": 24,
        },
        resident,
    )

    assert (status, reply) == (101, {"terminal_id": "t1"})
    assert resident.terminal_calls == [
        ("exec", "h1", "d1", ["psql", "app"], False, 80, 24)
    ]


def test_an_exec_the_resident_refuses_is_its_code():
    resident = FakeResident()
    resident.terminal_reply = {"code": "unknown_terminal", "params": {}}

    status, reply = routes.dispatch(
        "POST", "/api/terminal/exec", {"hub_id": "h1", "device_id": "x"}, resident
    )

    assert status == 404
    assert reply["code"] == "unknown_terminal"
    assert resident.terminal_calls == [("exec", "h1", "x", [], False, 0, 0)]


def test_a_persist_names_only_the_flags_its_body_carries():
    resident = FakeResident()

    by_terminal = routes.dispatch(
        "POST",
        "/api/terminal/persist",
        {"terminal_id": "t1", "is_shared": False},
        resident,
    )
    by_session = routes.dispatch(
        "POST",
        "/api/terminal/persist",
        {"hub_id": "h1", "session_id": "k1", "is_persistent": True},
        resident,
    )

    assert (by_terminal, by_session) == ((200, {}), (200, {}))
    assert resident.terminal_calls == [
        ("persist", "t1", None, False),
        ("persist_session", "h1", "k1", True, None),
    ]


def test_attaching_to_a_machine_the_hub_does_not_offer_is_404():
    resident = FakeResident()
    resident.terminal_reply = {"code": "unknown_terminal", "params": {}}

    status, reply = routes.dispatch(
        "POST", "/api/terminal/attach", {"hub_id": "h1", "device_id": "x"}, resident
    )

    assert status == 404
    assert reply["code"] == "unknown_terminal"


def test_the_output_of_an_open_terminal_answers_101_and_another_404():
    resident = FakeResident()

    assert routes.dispatch(
        "POST", "/api/terminal/output", {"terminal_id": "t1"}, resident
    ) == (101, {"terminal_id": "t1"})
    assert (
        routes.dispatch(
            "POST", "/api/terminal/output", {"terminal_id": "t9"}, resident
        )[0]
        == 404
    )


def test_a_resize_reaches_the_resident_and_nothing_launches_a_terminal():
    resident = FakeResident()

    resize = routes.dispatch(
        "POST",
        "/api/terminal/resize",
        {"terminal_id": "t1", "cols": 100, "rows": "30"},
        resident,
    )
    launch = routes.dispatch(
        "POST",
        "/api/terminal/launch",
        {"hub_id": "h1", "device_id": "d_lepton"},
        resident,
    )

    assert resize[0] == 200
    assert launch == (404, {"code": "unknown_request", "params": {}})
    assert resident.terminal_calls == [("resize", "t1", 100, 30)]


def test_the_windows_terminal_opens_with_its_size_and_answers_its_id():
    resident = FakeResident()

    opened = routes.dispatch(
        "POST",
        "/api/terminal/open",
        {"hub_id": "h1", "device_id": "d_lepton", "cols": 132, "rows": 43},
        resident,
    )

    assert opened == (200, {"terminal_id": "t1"})
    assert resident.terminal_calls == [("window", "h1", "d_lepton", 132, 43)]
    resident.terminal_reply = {"code": "unknown_terminal", "params": {}}
    assert (
        routes.dispatch(
            "POST", "/api/terminal/open", {"hub_id": "h1", "device_id": "x"}, resident
        )[0]
        == 404
    )


def test_a_kept_session_is_opened_by_its_id():
    resident = FakeResident()

    routes.dispatch(
        "POST",
        "/api/terminal/open",
        {"hub_id": "h1", "device_id": "d1", "cols": 80, "rows": 24, "session_id": "k1"},
        resident,
    )

    assert resident.terminal_calls == [("window", "h1", "d1", 80, 24, "k1")]


def test_persist_and_stop_reach_the_resident_and_answer_empty():
    resident = FakeResident()

    persisted = routes.dispatch(
        "POST",
        "/api/terminal/persist",
        {"terminal_id": "t1", "is_persistent": True, "is_shared": True},
        resident,
    )
    stopped = routes.dispatch(
        "POST", "/api/terminal/stop", {"hub_id": "h1", "session_id": "k1"}, resident
    )

    assert (persisted, stopped) == ((200, {}), (200, {}))
    assert resident.terminal_calls == [
        ("persist", "t1", True, True),
        ("stop", "h1", "k1"),
    ]


@pytest.mark.parametrize("code", ["session_unknown", "session_not_owned"])
def test_a_refused_session_step_answers_its_code(code):
    resident = FakeResident()
    resident.session_reply = {"code": code, "params": {"session_id": "k1"}}

    status, reply = routes.dispatch(
        "POST", "/api/terminal/stop", {"hub_id": "h1", "session_id": "k1"}, resident
    )

    assert status == 400
    assert reply == {"code": code, "params": {"session_id": "k1"}}


def test_the_windows_keys_arrive_as_base64_and_reach_the_shell_as_bytes():
    resident = FakeResident()
    typed = base64.b64encode("ls é\r".encode()).decode()

    sent = routes.dispatch(
        "POST", "/api/terminal/input", {"terminal_id": "t1", "data": typed}, resident
    )
    garbled = routes.dispatch(
        "POST", "/api/terminal/input", {"terminal_id": "t1", "data": "@@"}, resident
    )
    unknown = routes.dispatch(
        "POST", "/api/terminal/input", {"terminal_id": "t9", "data": typed}, resident
    )

    assert sent == (200, {})
    assert resident.typed == ["ls é\r".encode()]
    assert garbled == (404, {"code": "unknown_request", "params": {}})
    assert unknown[0] == 404


def test_clear_on_the_windows_terminal_reaches_the_resident():
    resident = FakeResident()

    cleared = routes.dispatch(
        "POST", "/api/terminal/clear", {"terminal_id": "t1"}, resident
    )
    unknown = routes.dispatch(
        "POST", "/api/terminal/clear", {"terminal_id": "t9"}, resident
    )

    assert cleared == (200, {})
    assert unknown == (404, {"code": "unknown_terminal", "params": {}})
    assert resident.terminal_calls == [("clear", "t1"), ("clear", "t9")]


def test_panel_reaches_the_resident_and_answers_the_state_or_its_refusal():
    resident = FakeResident()

    status, state = routes.dispatch(
        "POST", "/api/panel/open", {"hub_id": "h1"}, resident
    )
    resident.panel_reply = {"code": "permission_denied", "params": {"kind": "panel"}}
    refused = routes.dispatch("POST", "/api/panel/open", {"hub_id": "h2"}, resident)

    assert status == 200 and "hubs" in state
    assert refused == (400, {"code": "permission_denied", "params": {"kind": "panel"}})
    assert resident.panel_opens == ["h1", "h2"]


def test_closing_the_windows_terminal_reaches_the_resident():
    resident = FakeResident()

    assert routes.dispatch(
        "POST", "/api/terminal/close", {"terminal_id": "t1"}, resident
    ) == (200, {})
    assert (
        routes.dispatch("POST", "/api/terminal/close", {"terminal_id": "t9"}, resident)[
            0
        ]
        == 404
    )
    assert resident.terminal_calls == [("close", "t1"), ("close", "t9")]


def test_the_result_names_how_the_shell_ended():
    resident = FakeResident()

    assert routes.dispatch(
        "POST", "/api/terminal/result", {"terminal_id": "t1"}, resident
    ) == (200, {"exit_code": 0})


# --- the clipboard and the terminal's font ---


def test_the_clipboard_route_answers_the_text_the_resident_read():
    resident = FakeResident()

    assert routes.dispatch("GET", "/api/clipboard", None, resident) == (
        200,
        {"text": "echo pasted\n"},
    )


def test_a_clipboard_that_cannot_be_read_answers_its_code():
    resident = FakeResident()
    resident.clipboard_reply = {
        "code": "clipboard_unreadable",
        "params": {"detail": "busy"},
    }

    status, reply = routes.dispatch("GET", "/api/clipboard", None, resident)

    assert status == 400
    assert reply == {"code": "clipboard_unreadable", "params": {"detail": "busy"}}


def test_the_resident_words_a_clipboard_the_platform_cannot_read():
    from neutrino_client.core.resident import ClientResident

    class Unreadable(FakeClientPlatform):
        def read_clipboard(self):
            raise OSError("no display")

    class Readable(FakeClientPlatform):
        def read_clipboard(self):
            return "pwd"

    resident = ClientResident.__new__(ClientResident)
    resident.platform = Unreadable()
    assert resident.read_clipboard() == {
        "code": "clipboard_unreadable",
        "params": {"detail": "no display"},
    }
    resident.platform = Readable()
    assert resident.read_clipboard() == {"text": "pwd"}


def test_the_font_is_served_in_pieces_that_add_up_to_the_file():
    whole = (page.gui_dir() / page.GUI_TERMINAL_FONTS["regular"]).read_bytes()
    pieces = []
    offset = 0
    while offset < len(whole):
        status, reply = routes.dispatch(
            "GET", f"/api/font?name=regular&offset={offset}", None, FakeResident()
        )
        assert status == 200
        assert reply["offset"] == offset and reply["size"] == len(whole)
        piece = base64.b64decode(reply["data"])
        assert 0 < len(piece) <= page.GUI_FONT_CHUNK_BYTES
        pieces.append(piece)
        offset += len(piece)

    assert b"".join(pieces) == whole
    assert len(pieces) > 1


@pytest.mark.parametrize(
    "query", ["name=../../etc/passwd", "name=", "name=regular&offset=x"]
)
def test_a_font_the_page_does_not_carry_is_an_unknown_request(query):
    status, reply = routes.dispatch("GET", "/api/font?" + query, None, FakeResident())

    assert status == 404
    assert reply["code"] == "unknown_request"


def test_the_terminal_font_size_is_kept_and_stated():
    resident = FakeResident()

    status, state = routes.dispatch(
        "POST", "/api/terminal/font", {"size": 15}, resident
    )

    assert status == 200
    assert state["terminal_font_size"] == 15


def test_a_quit_for_an_upgrade_arranges_the_return_before_it_shuts_down(
    quit_without_ending,
):
    resident = FakeResident()

    status, _ = routes.dispatch("POST", "/api/quit", {"is_upgrade": True}, resident)

    assert status == 200
    assert resident.relaunches == 1
    assert resident.is_shut_down.wait(timeout=5)

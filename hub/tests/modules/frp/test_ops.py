"""Running frpc for a picked tunnel, its states, the tunnel list and the login.

The applier against a fake controller and recorded vendor answers: a
missing file is fetched and written root-only, frpc runs from the unit
template on Linux and from a start line elsewhere, and turning the way in
off or forgetting the account stops it and deletes the file. The monitor
turns frpc's lines and the check from outside into network.md's states.
OpenFrp's login polls every 5 seconds and ends at 5 minutes on a fake
clock, and stores what the person confirmed sealed.
"""

import base64
import json
import stat

import pytest
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey

from neutrino_hub.modules.frp import ops
from neutrino_hub.modules.frp.config import FrpConfig, read_frp, write_frp
from neutrino_hub.modules.frp.constants import (
    FRP_OPENFRP,
    FRP_OPENFRP_LOGIN_POLL_URL,
    FRP_OPENFRP_LOGIN_REQUEST_URL,
    FRP_SAKURAFRP,
    FRP_SAKURAFRP_API,
)
from neutrino_hub.modules.frp.nacl_box import box_seal
from neutrino_hub.modules.frp.ops import (
    FrpApplier,
    FrpMonitor,
    OpenFrpLogin,
    frp_file,
    listed_tunnels,
    reseal_authorization,
    vendor_api,
)
from neutrino_hub.system.process_control import ServiceStatus
from tests.conftest import FakeClock, unlock_vault
from tests.modules.frp.fake_vendors import (
    OPENFRP_AUTHORIZATION,
    SAKURAFRP_KEY,
    FakeVendors,
    answer,
)

OWN_FINGERPRINT = "a" * 64


class FakeController:
    """The process controller, recording each verb on a frpc."""

    def __init__(self):
        self.calls: list = []
        self.is_running = False
        self.is_on = False
        self.process_ids: list = []
        self.output: list = []

    def status(self, name):
        return ServiceStatus(name, name, True, self.is_running, self.is_on)

    def is_active(self, name):
        return self.is_running

    def is_enabled(self, name):
        return self.is_on

    def set_start_line(self, name, argv, env, cwd):
        self.calls.append(("start_line", name, argv))

    def enable(self, name):
        self.calls.append(("enable", name))
        self.is_on = True

    def disable(self, name):
        self.calls.append(("disable", name))
        self.is_on = False
        self.is_running = False

    def restart(self, name):
        self.calls.append(("restart", name))
        self.is_running = True

    def stop(self, name):
        self.calls.append(("stop", name))
        self.is_running = False

    def reload(self):
        self.calls.append(("reload",))

    def process_id(self, name):
        if self.process_ids:
            return (
                self.process_ids.pop(0)
                if len(self.process_ids) > 1
                else (self.process_ids[0])
            )
        return 0

    def run_output(self, name, *, line_count):
        return list(self.output)


@pytest.fixture
def box(monkeypatch, tmp_path):
    """A Linux hub with an unlocked vault, frpc carried, and both vendors
    signed in with a tunnel picked."""
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    unlock_vault(monkeypatch, tmp_path)
    state = tmp_path / "state"
    systemd = tmp_path / "systemd"
    systemd.mkdir()
    frpc = tmp_path / "bin" / "frpc"
    frpc.parent.mkdir()
    frpc.write_text("#!/bin/sh\n")
    monkeypatch.setattr(ops, "UTILS_STATE_ROOT", state)
    monkeypatch.setattr(ops, "SYSTEM_SYSTEMD_DIR", systemd)
    monkeypatch.setattr(ops, "FRP_BINARY_PATH", frpc)
    monkeypatch.setattr(ops, "is_linux", lambda: True)
    monkeypatch.setattr(ops, "is_dev_root_set", lambda: False)
    vendors = FakeVendors()
    monkeypatch.setattr("neutrino_hub.modules.frp.vendor_api.http_call", vendors)
    for vendor, credential, tunnel_id in (
        (FRP_SAKURAFRP, SAKURAFRP_KEY, "114514"),
        (FRP_OPENFRP, OPENFRP_AUTHORIZATION, "120623"),
    ):
        config = FrpConfig(
            vendor=vendor,
            is_enabled=True,
            tunnel_id=tunnel_id,
            node_name="node",
            local_port=8443,
            public_host="frp-a.natfrp.cloud",
            public_port=41234,
        )
        config.set_credential(credential)
        write_frp(config)
    return {"systemd": systemd, "vendors": vendors, "frpc": frpc, "tmp": tmp_path}


def applier(controller, vendor=FRP_SAKURAFRP, **monitor_keywords):
    monitor = FrpMonitor(
        vendor=vendor,
        controller=controller,
        fingerprint_of=lambda: OWN_FINGERPRINT,
        **monitor_keywords,
    )
    return FrpApplier(controller=controller, monitor=monitor), monitor


# --- the apply ----------------------------------------------------------------


def test_a_missing_file_is_fetched_written_root_only_and_frpc_started(box):
    controller = FakeController()
    apply, _ = applier(controller)

    change = apply.apply(read_frp(FRP_SAKURAFRP))

    path = frp_file(FRP_SAKURAFRP)
    assert change == "frp_started"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    text = path.read_text()
    assert "localPort = 18443" in text
    assert 'localIP = "127.0.0.1"' in text
    assert "plugin" not in text and "webServer" not in text
    assert controller.calls[-2:] == [("enable", "sakurafrp"), ("restart", "sakurafrp")]
    unit = (box["systemd"] / "neutrino_hub_sakurafrp.service").read_text()
    assert (
        "ExecStart=/opt/neutrino/hub/bin/frpc -c "
        "/var/lib/neutrino/hub/sakurafrp/frpc.toml"
    ) in unit
    assert "ConditionPathExists=/var/lib/neutrino/hub/sakurafrp/frpc.toml" in unit


def test_the_fetch_finds_the_tunnel_whatever_its_local_port_now(box):
    """A tunnel whose local port is no longer the connection port keeps
    running, so a box restored from config/ fetches it all the same."""
    config = read_frp(FRP_SAKURAFRP)
    config.tunnel_id = "114516"
    write_frp(config)
    box["vendors"].answers[("POST", f"{FRP_SAKURAFRP_API}/tunnel/config")] = answer(
        'serverAddr = "frp-a.natfrp.cloud"\n[[proxies]]\nname = "ssh"\n'
        'type = "tcp"\nremotePort = 41235\n'
    )
    apply, _ = applier(FakeController())

    apply.apply(read_frp(FRP_SAKURAFRP))

    assert "remotePort = 41235" in frp_file(FRP_SAKURAFRP).read_text()


def test_openfrps_file_comes_from_the_tunnels_node(box):
    controller = FakeController()
    apply, _ = applier(controller, FRP_OPENFRP)

    apply.apply(read_frp(FRP_OPENFRP))

    text = frp_file(FRP_OPENFRP).read_text()
    assert 'name = "neutrino"' in text and 'name = "mc"' not in text
    assert "localPort = 18444" in text
    sent = [
        json.loads(body)
        for _, url, _, body in box["vendors"].requests
        if url.endswith("getNodeConf")
    ]
    assert sent == [{"node_id": 41}]


def test_a_running_frpc_with_its_file_is_left_alone_unless_asked(box):
    controller = FakeController()
    apply, _ = applier(controller)
    apply.apply(read_frp(FRP_SAKURAFRP))
    controller.calls.clear()
    asked = len(box["vendors"].requests)

    assert apply.apply(read_frp(FRP_SAKURAFRP)) == ""
    assert apply.apply(read_frp(FRP_SAKURAFRP), is_restarted=True) == "frp_started"
    assert controller.calls == [("restart", "sakurafrp")]
    assert len(box["vendors"].requests) == asked


def test_turning_the_way_in_off_stops_frpc_and_deletes_its_file(box):
    controller = FakeController()
    apply, _ = applier(controller)
    apply.apply(read_frp(FRP_SAKURAFRP))
    config = read_frp(FRP_SAKURAFRP)
    config.is_enabled = False

    change = apply.apply(config)

    assert change == "frp_stopped"
    assert ("stop", "sakurafrp") in controller.calls
    assert ("disable", "sakurafrp") in controller.calls
    assert not frp_file(FRP_SAKURAFRP).exists()


def test_forgetting_the_account_stops_frpc_and_deletes_its_file(box):
    controller = FakeController()
    apply, _ = applier(controller)
    apply.apply(read_frp(FRP_SAKURAFRP))
    config = read_frp(FRP_SAKURAFRP)
    config.forget()

    apply.apply(config)

    assert config.to_dict()["credential"] == {}
    assert (config.tunnel_id, config.public_host, config.is_enabled) == ("", "", True)
    assert not frp_file(FRP_SAKURAFRP).exists()


def test_macos_and_windows_hand_the_start_line_to_the_service(box, monkeypatch):
    monkeypatch.setattr(ops, "is_linux", lambda: False)
    controller = FakeController()
    apply, _ = applier(controller)

    apply.apply(read_frp(FRP_SAKURAFRP))

    assert controller.calls[0] == (
        "start_line",
        "sakurafrp",
        [str(box["frpc"]), "-c", str(frp_file(FRP_SAKURAFRP))],
    )
    assert not (box["systemd"] / "neutrino_hub_sakurafrp.service").exists()


def test_a_config_the_vendor_does_not_return_is_config_failed(box):
    box["vendors"].answers[("POST", f"{FRP_SAKURAFRP_API}/tunnel/config")] = answer(
        {"code": 404, "msg": "隧道不存在"}, status=500
    )
    controller = FakeController()
    apply, monitor = applier(controller)

    assert apply.apply(read_frp(FRP_SAKURAFRP)) == ""

    assert not frp_file(FRP_SAKURAFRP).exists()
    assert monitor.view()["state"] == "config_failed"
    assert monitor.view()["last_error"] == (
        "frp_vendor_unreachable: HTTP 500: 隧道不存在"
    )


def test_a_tunnel_gone_from_the_account_is_config_failed(box):
    config = read_frp(FRP_SAKURAFRP)
    config.tunnel_id = "999"
    write_frp(config)
    apply, monitor = applier(FakeController())

    apply.apply(read_frp(FRP_SAKURAFRP))

    assert monitor.view()["state"] == "config_failed"
    assert monitor.view()["last_error"] == "frp_tunnel_unknown"


# --- the states ---------------------------------------------------------------


def started(box, controller, **monitor_keywords):
    """Apply, then hand the monitor a running frpc."""
    apply, monitor = applier(controller, **monitor_keywords)
    apply.apply(read_frp(FRP_SAKURAFRP))
    return monitor


@pytest.mark.parametrize(
    ("change", "state"),
    [
        (lambda config: setattr(config, "is_enabled", False), "disabled"),
        (lambda config: config.forget(), "not_signed_in"),
        (lambda config: config.clear_tunnel(), "no_tunnel"),
    ],
)
def test_the_states_read_from_the_file_alone(box, change, state):
    config = read_frp(FRP_SAKURAFRP)
    change(config)
    write_frp(config)
    _, monitor = applier(FakeController())

    assert monitor.view()["state"] == state


def test_a_vault_that_cannot_open_the_credential_is_vault_locked(box):
    (box["tmp"] / "state" / "vault.key").unlink()
    _, monitor = applier(FakeController())

    assert monitor.view()["state"] == "vault_locked"


def test_a_listener_another_program_holds_is_loopback_port_taken(box):
    _, monitor = applier(FakeController(), is_listener_taken=lambda vendor: True)

    assert monitor.view()["state"] == "loopback_port_taken"


def test_frpc_running_before_its_first_check_is_connecting(box):
    controller = FakeController()
    monitor = started(box, controller)
    controller.process_ids = [41]

    assert monitor.view()["state"] == "connecting"


def test_the_check_meeting_the_hubs_certificate_is_connected(box):
    controller = FakeController()
    clock = FakeClock()
    checked = []

    def check(host, port, *, timeout_s):
        checked.append((host, port, timeout_s))
        return OWN_FINGERPRINT

    monitor = started(box, controller, check=check, clock=clock)
    controller.process_ids = [41]
    monitor.tick()
    clock.now += 4
    monitor.tick()
    clock.now += 1
    monitor.tick()

    assert checked == [("frp-a.natfrp.cloud", 41234, 10.0)]
    assert monitor.view()["state"] == "connected"
    assert monitor.view()["checked_at"]
    clock.now += 59
    monitor.tick()
    clock.now += 1
    monitor.tick()
    assert len(checked) == 2


@pytest.mark.parametrize(
    ("met", "error"),
    [
        ("", "no answer at frp-a.natfrp.cloud:41234"),
        ("b" * 64, "another certificate at frp-a.natfrp.cloud:41234"),
    ],
)
def test_a_check_meeting_nothing_or_another_certificate_is_port_closed(box, met, error):
    controller = FakeController()
    clock = FakeClock()
    monitor = started(
        box, controller, check=lambda host, port, *, timeout_s: met, clock=clock
    )
    controller.process_ids = [41]
    monitor.tick()
    clock.now += 5
    monitor.tick()

    assert monitor.view() == {
        "state": "port_closed",
        "last_error": error,
        "checked_at": monitor.view()["checked_at"],
    }


def test_a_tunnel_the_node_refused_is_proxy_refused(box):
    controller = FakeController()
    monitor = started(box, controller)
    controller.process_ids = [41]
    line = "[W] [control.go:2] [neutrino] start error: port already used"
    controller.output = ["[I] login to server success", line]

    assert monitor.view() == {
        "state": "proxy_refused",
        "last_error": line,
        "checked_at": "",
    }


@pytest.mark.parametrize(
    ("line", "state"),
    [
        ("[E] login to the server failed: authorization failed", "login_failed"),
        (
            "[E] login to the server failed: dial tcp 1.2.3.4:7001: i/o timeout",
            "unreachable",
        ),
    ],
)
def test_an_ended_frpc_is_judged_by_what_it_wrote(box, line, state):
    controller = FakeController()
    monitor = started(box, controller)
    controller.output = ["[I] start frpc service", line]

    assert monitor.view()["state"] == state
    assert monitor.view()["last_error"] == line


# --- the tunnel list ----------------------------------------------------------


def test_sakurafrps_rows_are_timed_at_the_port_each_config_names(box):
    dialled = []

    def dial(host, port):
        dialled.append((host, port))
        return 23

    api = vendor_api(read_frp(FRP_SAKURAFRP))
    rows = listed_tunnels(api, FRP_SAKURAFRP, agent_port=8443, dial=dial)

    assert [(row.name, latency) for row, latency in rows] == [
        ("neutrino", 23),
        ("hk", 23),
    ]
    assert sorted(dialled) == [
        ("frp-a.natfrp.cloud", 7001),
        ("frp-c.natfrp.cloud", 7001),
    ]


def test_a_node_with_no_address_or_no_connect_in_time_has_no_latency(box):
    api = vendor_api(read_frp(FRP_OPENFRP))

    rows = listed_tunnels(
        api,
        FRP_OPENFRP,
        agent_port=8443,
        dial=lambda host, port: None if host.startswith("jp") else 31,
    )

    assert [(row.name, latency) for row, latency in rows] == [
        ("neutrino", 31),
        ("tokyo", None),
    ]


def test_a_real_connect_is_timed_and_a_closed_port_is_none():
    import socket

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    try:
        assert ops.connect_ms("127.0.0.1", port) >= 1
    finally:
        listener.close()
    assert ops.connect_ms("127.0.0.1", port) is None


# --- OpenFrp's Authorization and its login ------------------------------------


def test_a_rotated_authorization_is_resealed_in_place_of_the_stored_one(box):
    api = vendor_api(read_frp(FRP_OPENFRP))
    box["vendors"].answers[("POST", "https://api.openfrp.net/frp/api/getNodeList")] = (
        answer(
            {"data": {"list": []}, "flag": True, "msg": "OK"},
            headers={"authorization": "OPENFRPsecond"},
        )
    )

    api.node_list()

    stored = read_frp(FRP_OPENFRP)
    assert stored.credential() == "OPENFRPsecond"
    assert "OPENFRPsecond" not in json.dumps(stored.to_dict())


def test_a_rotation_after_a_logout_stores_nothing(box):
    config = read_frp(FRP_OPENFRP)
    config.forget()
    write_frp(config)

    reseal_authorization("OPENFRPsecond")

    assert read_frp(FRP_OPENFRP).is_signed_in is False


class LoginClock:
    """A fake clock the login's wait moves, five seconds at a time."""

    def __init__(self):
        self.now = 0.0
        self.waits: list = []

    def __call__(self) -> float:
        return self.now

    def wait(self, seconds: float) -> bool:
        self.waits.append(seconds)
        self.now += seconds
        return False


def login_with(box, clock, **keywords):
    signed_in = []
    keywords.setdefault("spawn", lambda target, args: target(*args))
    login = OpenFrpLogin(
        on_signed_in=lambda: signed_in.append(True),
        clock=clock,
        wait=clock.wait,
        **keywords,
    )
    return login, signed_in


def test_the_login_is_polled_every_5_s_and_ends_at_5_minutes(box):
    clock = LoginClock()
    login, signed_in = login_with(box, clock)

    login.start()

    polls = [url for url in box["vendors"].urls() if url == FRP_OPENFRP_LOGIN_POLL_URL]
    assert set(clock.waits) == {5.0}
    assert len(polls) == 60
    assert clock.now == 300.0
    assert login.view() == {"state": "timed_out", "authorization_url": ""}
    assert signed_in == []


def test_a_confirmed_login_is_opened_and_stored_sealed(box):
    clock = LoginClock()
    server = X25519PrivateKey.generate()
    asked = {}

    def request_login(method, url, headers, body):
        asked["public_key"] = json.loads(body)["public_key"]
        return answer(
            {
                "code": 200,
                "data": {
                    "authorization_url": "https://x/confirm",
                    "request_uuid": "u1",
                },
            }
        )

    def poll(method, url, headers, body):
        if clock.now < 15:
            return answer(b"", status=204)
        hub_key = base64.urlsafe_b64decode(asked["public_key"])
        sealed = box_seal(
            b"OPENFRPconfirmed",
            bytes(24),
            peer_public=hub_key,
            own_private=server.private_bytes_raw(),
        )
        return answer(
            {
                "code": 200,
                "data": {"authorization_data": base64.b64encode(sealed).decode()},
            },
            headers={
                "x-request-public-key": base64.urlsafe_b64encode(
                    server.public_key().public_bytes_raw()
                ).decode()
            },
        )

    vendors = box["vendors"]
    vendors.answers[("POST", FRP_OPENFRP_LOGIN_REQUEST_URL)] = request_login
    vendors.answers[("GET", FRP_OPENFRP_LOGIN_POLL_URL)] = poll
    config = read_frp(FRP_OPENFRP)
    config.forget()
    write_frp(config)
    seen = []

    def spawn(target, args):
        seen.append(login.view())
        target(*args)

    login, signed_in = login_with(box, clock, spawn=spawn)
    login.is_expired = True

    login.start()

    assert seen == [{"state": "waiting", "authorization_url": "https://x/confirm"}]
    assert read_frp(FRP_OPENFRP).credential() == "OPENFRPconfirmed"
    assert login.view() == {"state": "idle", "authorization_url": ""}
    assert login.is_expired is False
    assert signed_in == [True]
    assert clock.now == 15.0


def test_an_answer_that_does_not_open_fails_the_login(box):
    clock = LoginClock()
    box["vendors"].answers[("GET", FRP_OPENFRP_LOGIN_POLL_URL)] = answer(
        {
            "code": 200,
            "data": {"authorization_data": base64.b64encode(bytes(60)).decode()},
        },
        headers={"x-request-public-key": base64.b64encode(bytes(32)).decode()},
    )
    login, signed_in = login_with(box, clock)

    login.start()

    assert login.view()["state"] == "failed"
    assert read_frp(FRP_OPENFRP).credential() == OPENFRP_AUTHORIZATION
    assert signed_in == []


def test_a_login_ended_while_waiting_stores_nothing(box):
    clock = LoginClock()
    login, _ = login_with(box, clock)
    login.end()

    assert login.view() == {"state": "idle", "authorization_url": ""}

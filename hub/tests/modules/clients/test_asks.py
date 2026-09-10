"""The asks a client may put, answered from the live shares and the seat passwords."""

from neutrino_hub.modules.clients.asks import answer_ask, catalog_frame
from neutrino_hub.modules.services.device_shares import DeviceShareRegistry

MAC = "aa:bb:cc:dd:ee:ff"


def shares_with_one() -> list:
    registry = DeviceShareRegistry()
    registry.declare(
        mac_address=MAC,
        share_id="s1",
        hostname="desk",
        host="192.168.100.7",
        port=21118,
    )
    return registry.live()


def seat_password_of(key: str) -> str:
    return "seat-pass" if key == MAC else ""


def ask(kind: str, **args) -> dict:
    return {"type": "ask", "id": "7", "kind": kind, "args": args}


def test_the_catalog_frame_hashes_what_it_carries_and_a_disabled_one_is_empty():
    services = [{"id": "web_gitea", "type": "web", "payload": {"url": "http://h"}}]

    frame = catalog_frame(services, is_disabled=False)
    empty = catalog_frame(services, is_disabled=True)

    assert frame["type"] == "catalog" and frame["services"] == services
    assert len(frame["hash"]) == 16
    assert frame["hash"] == catalog_frame(list(services), is_disabled=False)["hash"]
    assert empty["services"] == [] and empty["hash"] != frame["hash"]
    assert empty["hash"] == catalog_frame([], is_disabled=False)["hash"]


def test_rdp_connect_answers_host_port_and_the_seat_password():
    answer = answer_ask(
        ask("rdp_connect", service_id="rdp_s1"),
        is_disabled=False,
        shares=shares_with_one(),
        seat_password_of=seat_password_of,
    )

    assert answer == {
        "type": "answer",
        "id": "7",
        "result": {
            "host": "192.168.100.7",
            "port": 21118,
            "password": "seat-pass",
        },  # scan: allow
    }


def test_a_share_that_is_gone_and_an_id_that_is_no_rdp_entry_are_told_apart():
    gone = answer_ask(
        ask("rdp_connect", service_id="rdp_s9"),
        is_disabled=False,
        shares=shares_with_one(),
        seat_password_of=seat_password_of,
    )
    unknown = answer_ask(
        ask("rdp_connect", service_id="web_gitea"),
        is_disabled=False,
        shares=shares_with_one(),
        seat_password_of=seat_password_of,
    )

    assert gone["code"] == "rdp_not_shared" and gone["params"] == {
        "service_id": "rdp_s9"
    }
    assert unknown["code"] == "service_unknown"
    assert "result" not in gone and "result" not in unknown


def test_a_disabled_client_is_refused_every_ask_and_an_unknown_kind_is_named():
    refused = answer_ask(
        ask("rdp_connect", service_id="rdp_s1"),
        is_disabled=True,
        shares=shares_with_one(),
        seat_password_of=seat_password_of,
    )
    unknown = answer_ask(
        ask("teleport"), is_disabled=False, shares=[], seat_password_of=seat_password_of
    )

    assert refused == {
        "type": "answer",
        "id": "7",
        "code": "client_disabled",
        "params": {},
    }
    assert unknown["code"] == "ask_unknown" and unknown["params"] == {
        "kind": "teleport"
    }

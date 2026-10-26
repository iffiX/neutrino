"""Enrollment as one person: the link, the bindings kept, and their keys.

The payload is compact JSON compressed with zlib in unpadded base64url, so
the link holds no character a shell splits or a URL escapes; it carries the
hub's addresses as ``tcp://``, the ticket and the hub's static key, and a
link whose role is not ``client`` is refused. A join stores a pending
binding at once, with the link's ticket and key, its first address, every
address, its overlays and a static key of its own, and asks no hub; the
transport spends the ticket, and the binding then takes the hub's id and
token in the pending one's place, with no ticket. The psk is the token's
SHA-256; a 0.5 binding, pinned by a fingerprint, is moved to the hub's key
with its addresses written as ``tcp://``. The file is written atomically
and 0600 in the person's own configuration directory; a file of the older
single-binding shape reads as no bindings, and a binding without the
address list reads as one with none. The hub's name as a candidate and the
notes a session writes onto its binding are pinned here too. The link's
overlay objects are kept on the binding in the hub's order with only their
providers' own fields, one per provider, an unknown provider dropped; the
wish and the pick are kept per binding.
"""

import base64
import hashlib
import json
import os
import urllib.parse
import zlib

import pytest

import neutrino_client.core.enrollment as enrollment
import neutrino_client.core.files as files
from neutrino_client import CLIENT_VERSION
from neutrino_client.constants import PROTOCOL
from neutrino_client.core.enrollment import default_source_address, parse_link
from neutrino_client.exceptions import EnrollmentError
from tests.conftest import BINDING, HUB_KEY, link_for

KEY = HUB_KEY
SECOND = dict(
    BINDING,
    id="c2",
    hub_id="h2",
    hub_name="office",
    gateway_url="tcp://office.lan:8443",
    token="tok2",
)


def link(**payload) -> str:
    """A client link with the hub's key, over the payload given."""
    return link_for(dict({"key": KEY}, **payload))


def test_a_link_round_trips():
    urls, token, hub_key, _ = parse_link(
        link_for(
            {"urls": ["tcp://192.168.100.1:8443"], "token": "abc123", "key": "AB" * 32}
        )
    )
    assert urls == ["tcp://192.168.100.1:8443"]
    assert token == "abc123"
    assert hub_key == "ab" * 32


def test_every_address_the_hub_answers_on_is_carried_in_its_order():
    urls, _, _, _ = parse_link(
        link(urls=["tcp://192.168.8.1:8443", "tcp://10.0.0.1:8443"], token="t")
    )
    assert urls == ["tcp://192.168.8.1:8443", "tcp://10.0.0.1:8443"]


def test_an_address_of_another_scheme_is_skipped():
    urls, _, _, _ = parse_link(
        link(urls=["quic://192.168.8.1:8443", "tcp://10.0.0.1:8443"], token="t")
    )
    assert urls == ["tcp://10.0.0.1:8443"]


def test_the_link_needs_no_quoting():
    made = link(urls=["tcp://192.168.100.1:8443"], token="t" * 24)
    assert not any(character in made for character in "?&%#;|<> '\"")


def test_the_bare_payload_is_accepted():
    payload = link(urls=["tcp://gateway:8443"], token="t").split("/")[-1]
    urls, token, _, _ = parse_link(payload)
    assert (urls, token) == (["tcp://gateway:8443"], "t")


@pytest.mark.parametrize(
    "text, code",
    [
        ("", "link_missing"),
        ("not a link at all", "link_unreadable"),
        ("neutrino://enroll/not-base64!!", "link_unreadable"),
        ("neutrino://enroll?url=http%3A%2F%2Fold&token=style", "link_unreadable"),
    ],
)
def test_what_is_not_a_link_is_refused_typed(text, code):
    with pytest.raises(EnrollmentError) as caught:
        parse_link(text)
    assert caught.value.code == code


@pytest.mark.parametrize(
    "payload",
    [
        {"urls": ["tcp://gateway:8443"], "key": KEY},
        {"token": "t", "key": KEY},
        {"urls": ["tcp://gateway:8443"], "token": "t"},
        {"urls": ["tcp://gateway:8443"], "token": "t", "key": "ab"},
        {"urls": ["https://gateway:8443"], "token": "t", "key": KEY},
    ],
)
def test_a_link_missing_an_address_a_ticket_or_a_key_is_incomplete(payload):
    with pytest.raises(EnrollmentError) as caught:
        parse_link(link_for(payload))
    assert caught.value.code == "link_incomplete"


def test_a_link_of_0_5_carrying_a_fingerprint_is_incomplete():
    with pytest.raises(EnrollmentError) as caught:
        parse_link(
            link_for({"urls": ["https://g:8443"], "token": "t", "fp": "ab" * 32})
        )
    assert caught.value.code == "link_incomplete"


def test_a_device_agents_link_is_refused():
    with pytest.raises(EnrollmentError) as caught:
        parse_link(
            link_for({"urls": ["tcp://g:1"], "token": "t", "key": KEY, "role": "agent"})
        )
    assert caught.value.code == "link_not_for_client"
    assert caught.value.params == {"role": "agent"}


def test_a_link_that_does_not_inflate_or_parse_is_unreadable():
    body = {"urls": ["tcp://g:1"], "token": "t", "role": "client", "key": KEY}
    plain = base64.urlsafe_b64encode(json.dumps(body).encode()).decode()
    garbled = base64.urlsafe_b64encode(zlib.compress(b"{not json", 9)).decode()
    for text in (plain, garbled):
        with pytest.raises(EnrollmentError) as caught:
            parse_link("neutrino://enroll/" + text.rstrip("="))
        assert caught.value.code == "link_unreadable"


# --- joining ---


def pending(made=None) -> dict:
    """A join stored from a link, nothing asked of any hub."""
    return enrollment.enroll(
        made or link(urls=["tcp://hub:8443", "tcp://10.0.0.1:8443"], token="ticket")
    )


def test_a_join_stores_the_binding_at_once_with_a_key_of_its_own():
    binding = enrollment.enroll(
        link(
            urls=["tcp://hub:8443", "tcp://10.0.0.1:8443"],
            token="ticket",
            overlays=[EASYTIER],
        )
    )
    assert binding["id"].startswith("pending_")
    assert len(binding["private_key"]) == 64 and enrollment.is_key(
        binding["private_key"]
    )
    assert binding == {
        "id": binding["id"],
        "name": enrollment.socket.gethostname(),
        "hub_id": "",
        "hub_name": "",
        "gateway_url": "tcp://hub:8443",
        "gateway_urls": ["tcp://hub:8443", "tcp://10.0.0.1:8443"],
        "hub_key": KEY,
        "private_key": binding["private_key"],
        "fingerprint": "",
        "token": "",
        "ticket": "ticket",
        "is_pending": True,
        "overlays": [EASYTIER],
        "is_overlay_on": False,
        "overlay_pick": "",
    }
    assert enrollment.bindings() == [binding]


def test_two_joins_make_two_keys():
    assert pending()["private_key"] != pending()["private_key"]


def test_the_join_fields_are_the_protocols_seven():
    payload = enrollment.join_payload("ticket")
    assert set(payload) == {
        "ticket",
        "role",
        "protocol",
        "machine_id",
        "name",
        "software",
        "platform",
    }
    assert payload["role"] == "client"
    assert payload["protocol"] == PROTOCOL
    assert payload["machine_id"] == enrollment._machine_id()
    assert payload["software"] == f"neutrino_client/{CLIENT_VERSION}"
    assert set(payload["platform"]) == {"os", "family", "arch"}


def test_a_completed_join_takes_the_hubs_id_and_token_and_drops_the_ticket():
    binding = pending()
    completed = enrollment.joined_binding(binding, "c1", "tok")
    assert completed["id"] == "c1" and completed["token"] == "tok"
    assert "ticket" not in completed and "is_pending" not in completed
    assert completed["private_key"] == binding["private_key"]


@pytest.mark.parametrize("binding_id, token", [("", "tok"), ("c1", "")])
def test_a_join_answer_without_an_id_and_a_token_is_refused(binding_id, token):
    with pytest.raises(EnrollmentError) as caught:
        enrollment.joined_binding(pending(), binding_id, token)
    assert caught.value.code == "enroll_no_token"


def test_a_completed_join_takes_the_pending_ones_place(config_path):
    binding = pending()
    enrollment.add_binding(SECOND)
    enrollment.replace_binding(
        binding["id"], enrollment.joined_binding(binding, "c1", "tok")
    )
    assert [held["id"] for held in enrollment.bindings()] == ["c1", "c2"]
    stored = json.loads(config_path.read_text())["bindings"][0]
    assert "ticket" not in stored and "is_pending" not in stored


def test_a_completed_join_of_a_hub_already_held_replaces_it():
    enrollment.add_binding(BINDING)
    binding = pending()
    enrollment.replace_binding(
        binding["id"], enrollment.joined_binding(binding, "c1", "fresh")
    )
    (held,) = enrollment.bindings()
    assert (held["id"], held["token"]) == ("c1", "fresh")


def test_the_binding_lands_0600_in_the_persons_own_directory(config_path):
    pending()
    assert oct(config_path.stat().st_mode & 0o777) == "0o600"
    assert oct(config_path.parent.stat().st_mode & 0o777) == "0o700"
    written = json.loads(config_path.read_text())
    assert written["bindings"][0]["ticket"] == "ticket"
    assert written["exit_hub_id"] == ""


def test_the_file_is_replaced_whole_never_written_in_place(monkeypatch, config_path):
    replaced = []
    original = os.replace

    def spy(source, target):
        replaced.append((source, target))
        original(source, target)

    monkeypatch.setattr(files.os, "replace", spy)
    enrollment.add_binding(BINDING)
    assert len(replaced) == 1
    source, target = replaced[0]
    assert target == str(config_path)
    assert not os.path.exists(source)
    assert sorted(os.listdir(str(config_path.parent))) == ["client.json"]


def test_a_pending_binding_without_its_ticket_is_not_one(config_path):
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(
            {
                "bindings": [
                    {
                        "id": "p1",
                        "gateway_url": "tcp://a:1",
                        "hub_key": KEY,
                        "is_pending": True,
                    },
                    {
                        "id": "p2",
                        "gateway_url": "tcp://a:1",
                        "hub_key": KEY,
                        "is_pending": True,
                        "ticket": "t",
                    },
                ]
            }
        )
    )
    assert [held["id"] for held in enrollment.bindings()] == ["p2"]


# --- the keys ---


def test_the_psk_is_the_tokens_sha256_in_hex():
    assert enrollment.psk_of(BINDING) == hashlib.sha256(b"tok").hexdigest()


def test_a_binding_with_a_fingerprint_and_no_key_is_one_of_0_5():
    assert enrollment.is_legacy(dict(BINDING, hub_key="", fingerprint="ab" * 32))
    assert not enrollment.is_legacy(BINDING)


def test_a_moved_binding_takes_the_keys_and_its_addresses_as_tcp():
    legacy = dict(
        BINDING,
        hub_key="",
        private_key="",
        fingerprint="ab" * 32,
        gateway_url="https://hub.lan:8443",
        gateway_urls=["https://hub.lan:8443", "https://[2001:db8::1]:8443"],
    )
    moved = enrollment.moved_binding(legacy, "33" * 32, "44" * 32)
    assert moved["hub_key"] == "33" * 32 and moved["private_key"] == "44" * 32
    assert moved["fingerprint"] == ""
    assert moved["gateway_url"] == "tcp://hub.lan:8443"
    assert moved["gateway_urls"] == ["tcp://hub.lan:8443", "tcp://[2001:db8::1]:8443"]
    assert moved["token"] == "tok" and moved["id"] == "c1"


def test_a_binding_with_neither_a_key_nor_a_fingerprint_is_not_one(config_path):
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps({"bindings": [dict(BINDING, hub_key="")]}))
    assert enrollment.bindings() == []


# --- the candidates ---


def test_only_tcp_addresses_are_dialled():
    assert enrollment.dialable_urls(
        ["tcp://a:1", "https://b:2", "quic://c:3", "tcp://", "tcp://[::1]:4"]
    ) == ["tcp://a:1", "tcp://[::1]:4"]


def test_the_hubs_name_is_a_candidate_at_a_stored_addresss_port():
    assert enrollment.hub_name_address("tcp://192.0.2.1:8443") == (
        "tcp://hub.neutrino.internal:8443"
    )
    assert enrollment.hub_name_address("tcp://hub.lan") == ""
    assert enrollment.hub_name_address("") == ""


# --- the bindings kept ---


def test_a_file_of_the_single_binding_shape_reads_as_unbound(config_path):
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(
            {
                "gateway_url": "https://hub.lan:8443",
                "token": "tok",
                "fingerprint": "ab" * 32,
                "client_id": "c1",
            }
        )
    )

    assert enrollment.bindings() == []
    assert enrollment.is_configured() is False
    assert enrollment.load_config() == {"bindings": [], "exit_hub_id": ""}


def test_a_binding_missing_its_id_url_or_token_is_not_one(config_path):
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(
            {
                "bindings": [
                    dict(BINDING, id=""),
                    dict(BINDING, gateway_url=""),
                    dict(BINDING, token=""),
                    "not a record",
                    SECOND,
                ]
            }
        )
    )

    assert enrollment.bindings() == [SECOND]


def test_adding_the_same_id_replaces_in_place():
    enrollment.add_binding(BINDING)
    enrollment.add_binding(SECOND)

    enrollment.add_binding(dict(BINDING, token="fresh", name="renamed"))

    assert enrollment.bindings() == [
        dict(BINDING, token="fresh", name="renamed"),
        SECOND,
    ]


def test_a_binding_keeps_only_its_own_fields():
    enrollment.add_binding(dict(BINDING, password="never"))  # scan: allow

    assert enrollment.bindings() == [BINDING]


def test_a_binding_without_the_address_list_reads_as_one_with_none(config_path):
    """A 0.3.0 file names the one address that answered its join."""
    stored = {key: value for key, value in BINDING.items() if key != "gateway_urls"}
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps({"bindings": [stored], "exit_hub_id": ""}))

    (binding,) = enrollment.bindings()

    assert binding == BINDING
    assert enrollment.stored_urls(binding) == ["tcp://127.0.0.1:9"]


def test_an_incomplete_binding_is_refused_before_it_is_written(config_path):
    with pytest.raises(ValueError):
        enrollment.add_binding(dict(BINDING, token=""))

    assert not config_path.exists()


def test_remove_binding_drops_one_and_leaves_the_rest():
    enrollment.add_binding(BINDING)
    enrollment.add_binding(SECOND)

    enrollment.remove_binding("c1")
    enrollment.remove_binding("nobody")

    assert enrollment.bindings() == [SECOND]
    assert enrollment.is_configured() is True


def test_one_binding_per_hub_id_is_kept_the_one_joined_last(config_path):
    enrollment.add_binding(BINDING)
    waiting = pending()
    enrollment.add_binding(SECOND)
    enrollment.add_binding(dict(BINDING, id="c3", token="tok3"))

    dropped = enrollment.drop_repeated_hubs()

    assert dropped == [BINDING]
    assert [binding["id"] for binding in enrollment.bindings()] == [
        waiting["id"],
        "c2",
        "c3",
    ]


def test_a_file_with_no_hub_held_twice_is_not_written(config_path):
    enrollment.add_binding(BINDING)
    enrollment.add_binding(SECOND)
    pending()
    before = config_path.stat().st_mtime_ns

    assert enrollment.drop_repeated_hubs() == []
    assert config_path.stat().st_mtime_ns == before


@pytest.mark.parametrize("needle", ["c2", "h2", "office"])
def test_find_binding_answers_to_the_binding_id_the_hub_id_and_its_name(needle):
    enrollment.add_binding(BINDING)
    enrollment.add_binding(SECOND)

    assert enrollment.find_binding(needle) == SECOND


def test_find_binding_and_binding_for_answer_none_for_a_stranger():
    enrollment.add_binding(BINDING)

    assert enrollment.find_binding("elsewhere") is None
    assert enrollment.find_binding("") is None
    assert enrollment.binding_for("h2") is None
    assert enrollment.binding_for("") is None


def test_binding_for_answers_to_the_hub_id():
    enrollment.add_binding(BINDING)
    enrollment.add_binding(SECOND)

    assert enrollment.binding_for("h1") == BINDING


def test_note_hub_writes_what_the_welcome_said():
    enrollment.add_binding(BINDING)

    enrollment.note_hub("c1", "h1", "home")
    enrollment.note_hub("nobody", "h9", "nowhere")

    binding = enrollment.bindings()[0]
    assert (binding["hub_id"], binding["hub_name"]) == ("h1", "home")
    assert enrollment.binding_for("h1") == binding


def test_the_notes_write_the_addresses_onto_one_binding():
    enrollment.add_binding(BINDING)
    enrollment.add_binding(SECOND)

    enrollment.note_urls("c1", [LAN_URL, OVERLAY_URL + "/", OVERLAY_URL])
    enrollment.note_url("c1", OVERLAY_URL)
    enrollment.note_url("nobody", LAN_URL)

    first, second = enrollment.bindings()
    assert first["gateway_url"] == OVERLAY_URL
    assert first["gateway_urls"] == [LAN_URL, OVERLAY_URL]
    assert second == SECOND


# --- the addresses, and the round's order ---

LAN_URL = "tcp://192.0.2.1:8443"
OVERLAY_URL = "tcp://100.64.0.1:8443"


def test_the_list_is_kept_clean_and_in_the_hubs_order():
    assert enrollment.clean_urls([LAN_URL + "/", " ", OVERLAY_URL, LAN_URL, 7, ""]) == [
        LAN_URL,
        OVERLAY_URL,
        "7",
    ]
    assert enrollment.clean_urls("not a list") == []
    assert enrollment.clean_urls(None) == []


def test_the_route_to_the_hub_is_read_off_the_first_literal():
    """A loopback address is routed on every machine; a name is skipped."""
    assert default_source_address(["tcp://hub.lan:8443", "tcp://127.0.0.1:9"]) == (
        "127.0.0.1"
    )
    assert default_source_address(["tcp://hub.lan:8443"]) == ""
    assert default_source_address([]) == ""


def test_the_exit_hub_round_trips_and_survives_the_bindings_changing():
    assert enrollment.exit_hub_id() == ""

    enrollment.set_exit_hub_id("h1")
    enrollment.add_binding(BINDING)
    enrollment.remove_binding("c1")

    assert enrollment.exit_hub_id() == "h1"
    assert enrollment.load_config() == {"bindings": [], "exit_hub_id": "h1"}


def test_the_stamp_moves_with_every_write(config_path):
    assert enrollment.config_stamp() == 0

    enrollment.add_binding(BINDING)
    first = enrollment.config_stamp()
    os.utime(str(config_path), (1, 1))
    enrollment.remove_binding("c1")

    assert first != 0
    assert enrollment.config_stamp() not in (0, first)


# --- the overlay object ---

NETBIRD = {
    "provider": "netbird",
    "setup_key": "KEY-1",  # scan: allow
    "management_url": "",
    "fqdn": "hub.netbird.cloud",
    "hub_address": "100.88.92.30",
}
EASYTIER = {
    "provider": "easytier",
    "mode": "manual",
    "network_name": "home",
    "network_secret": "s3cret",  # scan: allow
    "peer": "tcp://203.0.113.7:11010",
    "hub_address": "10.144.144.1",
}
CONSOLE = {
    "provider": "easytier",
    "mode": "console",
    "is_secure_mode": True,
    "config_server": "tcp://et-web.console.easytier.net:22020/etk_x",  # scan: allow
    "hub_address": "",
}


def test_a_link_without_overlays_carries_none():
    *_, overlays = parse_link(
        link_for({"urls": ["tcp://g:1"], "token": "t", "key": KEY})
    )

    assert overlays == []


@pytest.mark.parametrize(
    "material",
    [NETBIRD, EASYTIER, CONSOLE],
)
def test_a_link_carries_the_overlay_objects(material):
    *_, overlays = parse_link(
        link_for(
            {"urls": ["tcp://g:1"], "token": "t", "key": KEY, "overlays": [material]}
        )
    )

    assert overlays == [material]


def test_the_overlays_keep_the_hubs_order_and_one_object_per_provider():
    raw = [EASYTIER, {"provider": "zerotier"}, NETBIRD, CONSOLE]

    assert enrollment.clean_overlays(raw) == [EASYTIER, NETBIRD]
    assert enrollment.clean_overlays({"provider": "netbird"}) == []


def test_an_overlay_keeps_only_its_providers_fields():
    raw = dict(EASYTIER, peer=" tcp://203.0.113.7:11010/ ", extra="x", fqdn="y")

    assert enrollment.clean_overlay(raw) == EASYTIER


def test_an_easytier_object_with_no_mode_reads_as_a_manual_one():
    """A hub from before the console mode names neither mode nor address."""
    raw = {key: value for key, value in EASYTIER.items() if key != "mode"}
    del raw["hub_address"]

    assert enrollment.clean_overlay(raw) == dict(EASYTIER, hub_address="")


def test_a_console_object_keeps_its_address_and_its_secure_mode_as_a_bool():
    raw = dict(CONSOLE, is_secure_mode="yes", network_secret="z", peer="p")

    assert enrollment.clean_overlay(raw) == dict(CONSOLE, is_secure_mode=False)
    assert enrollment.clean_overlay(CONSOLE) == CONSOLE


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "netbird",
        {"provider": "zerotier", "network": "n"},
        dict(NETBIRD, setup_key=""),
        dict(EASYTIER, network_secret=""),
        dict(EASYTIER, peer=""),
        dict(EASYTIER, mode="cloud"),
        dict(CONSOLE, config_server=""),
    ],
)
def test_an_unreadable_overlay_reads_as_none(raw):
    assert enrollment.clean_overlay(raw) is None


def test_a_netbird_overlay_may_name_no_management_url_fqdn_or_address():
    raw = dict(NETBIRD, fqdn="", hub_address="")

    assert enrollment.clean_overlay(raw) == raw


def test_the_join_keeps_the_links_overlays_on_the_binding():
    binding = enrollment.enroll(
        link_for(
            {"urls": ["tcp://g:1"], "token": "t", "key": KEY, "overlays": [EASYTIER]}
        )
    )

    assert binding["overlays"] == [EASYTIER]
    assert enrollment.bindings()[0]["overlays"] == [EASYTIER]
    assert binding["is_overlay_on"] is False


def test_note_overlays_writes_and_clears_one_bindings_list():
    enrollment.add_binding(BINDING)
    enrollment.add_binding(SECOND)

    enrollment.note_overlays("c2", [NETBIRD, EASYTIER])
    assert [binding["overlays"] for binding in enrollment.bindings()] == [
        [],
        [NETBIRD, EASYTIER],
    ]
    enrollment.note_overlays("c2", [])

    assert enrollment.bindings()[1]["overlays"] == []


def test_the_wish_and_the_pick_are_kept_per_binding():
    enrollment.add_binding(BINDING)
    enrollment.add_binding(SECOND)

    enrollment.note_overlay_choice("c2", True, "easytier")

    first, second = enrollment.bindings()
    assert (first["is_overlay_on"], first["overlay_pick"]) == (False, "")
    assert (second["is_overlay_on"], second["overlay_pick"]) == (True, "easytier")


def test_a_wish_that_is_not_a_bool_reads_as_none():
    enrollment.add_binding(dict(BINDING, is_overlay_on="yes"))

    assert enrollment.bindings()[0]["is_overlay_on"] is False


def test_a_binding_file_with_overlays_is_0600(config_path):
    enrollment.add_binding(dict(BINDING, overlays=[NETBIRD]))

    assert config_path.stat().st_mode & 0o777 == 0o600


def test_a_link_s_ipv6_address_is_kept_in_brackets_and_split_by_the_url_reader():
    urls, _, _, _ = parse_link(
        link_for(
            {
                "urls": ["tcp://192.168.100.1:8443", "tcp://[2001:db8::1]:8443"],
                "token": "abc123",
                "key": KEY,
            }
        )
    )

    assert urls[1] == "tcp://[2001:db8::1]:8443"
    parts = urllib.parse.urlsplit(urls[1])
    assert (parts.hostname, parts.port) == ("2001:db8::1", 8443)


def test_the_source_address_is_read_off_an_ipv4_literal_only():
    assert default_source_address(["tcp://[2001:db8::1]:8443"]) == ""

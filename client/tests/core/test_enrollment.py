"""Enrollment as one person: the link, the join, and the bindings kept.

The payload rides base64url so the link holds no character a shell splits
or a URL escapes; a link whose role is not ``client`` is refused; the join
body is the protocol's seven fields and names no MAC; the reply lands as
one binding in a list, with every address the link carried, written
atomically and 0600 in the person's own configuration directory; a file of
the older single-binding shape reads as no bindings, and a binding without
the address list reads as one with none. The candidates of a connection
round, the hub's name in a stored address's scheme and port, and the notes
a session writes onto its binding are pinned here too. The link's overlay
object is kept on the binding with only its provider's own fields, an
unknown provider reading as none, and its secret never reaches the log.
"""

import base64
import json
import os

import pytest

import neutrino_client.core.channel as channel
import neutrino_client.core.enrollment as enrollment
import neutrino_client.core.files as files
from neutrino_client import CLIENT_VERSION
from neutrino_client.constants import CLIENT_JOIN_PATH, CLIENT_LEAVE_PATH, PROTOCOL
from neutrino_client.core.enrollment import (
    default_source_address,
    parse_link,
    resolve_hub_address,
)
from neutrino_client.exceptions import EnrollmentError
from tests.conftest import BINDING, link_for

SECOND = dict(
    BINDING,
    id="c2",
    hub_id="h2",
    hub_name="office",
    gateway_url="https://office.lan:8443",
    token="tok2",
)


def test_a_link_round_trips():
    urls, token, fingerprint, _ = parse_link(
        link_for(
            {
                "urls": ["https://192.168.100.1:8443"],
                "token": "abc123",
                "fp": "AB" * 32,
            }
        )
    )
    assert urls == ["https://192.168.100.1:8443"]
    assert token == "abc123"
    assert fingerprint == "ab" * 32


def test_every_address_the_hub_answers_on_is_carried():
    urls, token, _, _ = parse_link(
        link_for(
            {
                "urls": ["http://192.168.8.1:8080", "http://10.0.0.1:8080"],
                "token": "abc123",
            }
        )
    )

    assert urls == ["http://192.168.8.1:8080", "http://10.0.0.1:8080"]
    assert token == "abc123"


def test_the_link_needs_no_quoting():
    link = link_for({"urls": ["http://192.168.100.1:8080"], "token": "t" * 24})
    assert not any(character in link for character in "?&%#;|<> '\"")


def test_the_bare_payload_is_accepted():
    link = link_for({"urls": ["http://gateway:8080"], "token": "t"})
    payload = link.split("/")[-1]
    urls, token, _, _ = parse_link(payload)
    assert urls == ["http://gateway:8080"]
    assert token == "t"


def test_a_trailing_slash_is_trimmed():
    urls, _, _, _ = parse_link(
        link_for({"urls": ["http://gateway:8080/"], "token": "t"})
    )
    assert urls == ["http://gateway:8080"]


def test_a_link_without_a_fingerprint_carries_an_empty_one():
    _, _, fingerprint, _ = parse_link(
        link_for({"urls": ["http://gateway:8080"], "token": "t"})
    )
    assert fingerprint == ""


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


def test_a_payload_missing_its_half_is_refused():
    with pytest.raises(EnrollmentError) as caught:
        parse_link(link_for({"urls": ["http://gateway"]}))
    assert caught.value.code == "link_incomplete"
    with pytest.raises(EnrollmentError) as caught:
        parse_link(link_for({"token": "t"}))
    assert caught.value.code == "link_incomplete"


def test_a_device_agents_link_is_refused():
    body = {"urls": ["http://gateway"], "token": "t", "fp": "", "role": "agent"}
    encoded = base64.urlsafe_b64encode(json.dumps(body).encode()).decode()

    with pytest.raises(EnrollmentError) as caught:
        parse_link("neutrino://enroll/" + encoded.rstrip("="))

    assert caught.value.code == "link_not_for_client"
    assert caught.value.params == {"role": "agent"}


def test_a_link_naming_no_role_is_refused():
    body = {"urls": ["http://gateway"], "token": "t", "kind": "client"}
    encoded = base64.urlsafe_b64encode(json.dumps(body).encode()).decode()

    with pytest.raises(EnrollmentError) as caught:
        parse_link("neutrino://enroll/" + encoded.rstrip("="))

    assert caught.value.code == "link_not_for_client"


def answer_with(monkeypatch, *, reply=None, error=None):
    posted = []

    def post(self, path, payload):
        posted.append((path, payload))
        if error is not None:
            raise error
        return dict(reply or {})

    monkeypatch.setattr(channel.GatewayHttpChannel, "post", post)
    return posted


# --- joining ---


def test_the_join_body_is_the_protocols_seven_fields(monkeypatch):
    posted = answer_with(monkeypatch, reply={"id": "c1", "token": "tok"})
    link = link_for({"urls": ["https://hub:8443"], "token": "ticket", "fp": "ab" * 32})

    binding = enrollment.enroll(link)

    path, payload = posted[0]
    assert path == CLIENT_JOIN_PATH
    assert set(payload) == {
        "ticket",
        "role",
        "protocol",
        "machine_id",
        "name",
        "software",
        "platform",
    }
    assert payload["ticket"] == "ticket"
    assert payload["role"] == "client"
    assert payload["protocol"] == PROTOCOL
    assert payload["machine_id"] == enrollment._machine_id()
    assert payload["name"] == enrollment.socket.gethostname()
    assert payload["software"] == f"neutrino_client/{CLIENT_VERSION}"
    assert set(payload["platform"]) == {"os", "family", "arch"}
    assert "mac_addresses" not in payload and "token" not in payload
    assert binding == {
        "id": "c1",
        "name": payload["name"],
        "hub_id": "",
        "hub_name": "",
        "gateway_url": "https://hub:8443",
        "gateway_urls": ["https://hub:8443"],
        "fingerprint": "ab" * 32,
        "token": "tok",
        "overlay": None,
    }
    assert enrollment.bindings() == [binding]


def test_the_address_that_answered_is_the_one_stored(monkeypatch):
    calls = []

    def post(self, path, payload):
        calls.append(self._gateway_url)
        if len(calls) == 1:
            raise channel.GatewayUnreachable("down")
        return {"id": "c1", "token": "tok"}

    monkeypatch.setattr(channel.GatewayHttpChannel, "post", post)

    binding = enrollment.enroll(
        link_for({"urls": ["http://a", "http://b"], "token": "ticket"})
    )

    assert calls == ["http://a", "http://b"]
    assert binding["gateway_url"] == "http://b"
    assert binding["gateway_urls"] == ["http://a", "http://b"]


def test_the_binding_lands_0600_in_the_persons_own_directory(monkeypatch, config_path):
    answer_with(monkeypatch, reply={"id": "c1", "token": "tok"})

    enrollment.enroll(link_for({"urls": ["http://hub"], "token": "ticket"}))

    assert config_path.is_file()
    assert oct(config_path.stat().st_mode & 0o777) == "0o600"
    assert oct(config_path.parent.stat().st_mode & 0o777) == "0o700"
    written = json.loads(config_path.read_text())
    assert written["bindings"][0]["token"] == "tok"
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
    assert os.path.dirname(source) == str(config_path.parent)
    assert not os.path.exists(source)
    assert sorted(os.listdir(str(config_path.parent))) == ["client.json"]


def test_a_refused_ticket_is_typed(monkeypatch):
    answer_with(monkeypatch, error=channel.GatewayRefused("401"))

    with pytest.raises(EnrollmentError) as caught:
        enrollment.enroll(link_for({"urls": ["http://hub"], "token": "ticket"}))

    assert caught.value.code == "enroll_refused"
    assert enrollment.bindings() == []


@pytest.mark.parametrize("code", ["protocol_too_old", "protocol_too_new"])
def test_a_protocol_the_hub_does_not_speak_is_typed_with_its_numbers(monkeypatch, code):
    answer_with(
        monkeypatch,
        error=channel.GatewayProtocolRefused(code=code, peer=1, hub=2, minimum=2),
    )

    with pytest.raises(EnrollmentError) as caught:
        enrollment.enroll(link_for({"urls": ["http://hub"], "token": "ticket"}))

    assert caught.value.code == code
    assert caught.value.params == {"peer": 1, "hub": 2, "min": 2}
    assert enrollment.bindings() == []


def test_no_answering_address_is_typed_naming_them_all(monkeypatch):
    answer_with(monkeypatch, error=channel.GatewayUnreachable("down"))

    with pytest.raises(EnrollmentError) as caught:
        enrollment.enroll(
            link_for({"urls": ["http://a", "http://b"], "token": "ticket"})
        )

    assert caught.value.code == "hub_unreachable"
    assert caught.value.params["urls"] == "http://a, http://b"


@pytest.mark.parametrize("reply", [{"id": "c1"}, {"token": "tok"}, {}])
def test_a_reply_without_an_id_and_a_token_is_refused(monkeypatch, reply):
    answer_with(monkeypatch, reply=reply)

    with pytest.raises(EnrollmentError) as caught:
        enrollment.enroll(link_for({"urls": ["http://hub"], "token": "ticket"}))

    assert caught.value.code == "enroll_no_token"
    assert enrollment.bindings() == []


# --- leaving ---


def test_leave_posts_the_id_and_the_token_and_keeps_the_binding(monkeypatch):
    posted = answer_with(monkeypatch, reply={})
    enrollment.add_binding(BINDING)

    enrollment.leave(BINDING)

    assert posted == [(CLIENT_LEAVE_PATH, {"id": "c1", "token": "tok"})]
    assert enrollment.bindings() == [BINDING]


def test_leave_pins_the_bindings_own_fingerprint(monkeypatch):
    made = []

    def __init__(self, *, gateway_url, fingerprint=""):
        made.append((gateway_url, fingerprint))
        self._gateway_url = gateway_url
        self._fingerprint = fingerprint

    monkeypatch.setattr(channel.GatewayHttpChannel, "__init__", __init__)
    monkeypatch.setattr(channel.GatewayHttpChannel, "post", lambda self, p, b: {})

    enrollment.leave(dict(SECOND, fingerprint="cd" * 32))

    assert made == [("https://office.lan:8443", "cd" * 32)]


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


def test_a_binding_keeps_only_its_nine_fields():
    enrollment.add_binding(dict(BINDING, password="never"))  # scan: allow

    assert enrollment.bindings() == [BINDING]


def test_a_binding_without_the_address_list_reads_as_one_with_none(config_path):
    """A 0.3.0 file names the one address that answered its join."""
    stored = {key: value for key, value in BINDING.items() if key != "gateway_urls"}
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps({"bindings": [stored], "exit_hub_id": ""}))

    (binding,) = enrollment.bindings()

    assert binding == BINDING
    assert enrollment.stored_urls(binding) == ["http://127.0.0.1:9"]
    assert enrollment.candidate_urls(binding) == ["http://127.0.0.1:9"]


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


def test_note_hub_writes_what_the_welcome_said(monkeypatch):
    answer_with(monkeypatch, reply={"id": "c1", "token": "tok"})
    enrollment.enroll(link_for({"urls": ["http://hub"], "token": "ticket"}))

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

LAN_URL = "https://192.0.2.1:8443"
OVERLAY_URL = "https://100.64.0.1:8443"
NAME_URL = "https://192.0.2.9:8443"


def test_the_list_is_kept_clean_and_in_the_hubs_order():
    assert enrollment.clean_urls([LAN_URL + "/", " ", OVERLAY_URL, LAN_URL, 7, ""]) == [
        LAN_URL,
        OVERLAY_URL,
        "7",
    ]
    assert enrollment.clean_urls("not a list") == []
    assert enrollment.clean_urls(None) == []


def test_a_round_is_the_name_then_the_last_answer_then_the_rest():
    binding = {"gateway_url": OVERLAY_URL, "gateway_urls": [LAN_URL, OVERLAY_URL]}

    assert enrollment.candidate_urls(binding, NAME_URL) == [
        NAME_URL,
        OVERLAY_URL,
        LAN_URL,
    ]
    assert enrollment.candidate_urls(binding) == [OVERLAY_URL, LAN_URL]
    assert enrollment.candidate_urls(binding, LAN_URL) == [LAN_URL, OVERLAY_URL]
    assert enrollment.stored_urls(binding) == [LAN_URL, OVERLAY_URL]


def test_the_name_takes_the_stored_addresss_scheme_and_port(monkeypatch):
    monkeypatch.setattr(enrollment, "resolve_hub_address", lambda: "192.0.2.9")

    assert enrollment.hub_name_url(LAN_URL) == NAME_URL
    assert enrollment.hub_name_url("http://192.0.2.1:9") == "http://192.0.2.9:9"
    assert enrollment.hub_name_url("https://hub.lan") == "https://192.0.2.9:443"


def test_a_name_that_does_not_resolve_is_no_candidate(monkeypatch):
    monkeypatch.setattr(enrollment, "resolve_hub_address", lambda: "")

    assert enrollment.hub_name_url(LAN_URL) == ""


def test_the_name_is_looked_up_as_ipv4_only(monkeypatch):
    asked = []

    def getaddrinfo(host, port, family=0, kind=0, *rest):
        asked.append((host, family, kind))
        return [(family, kind, 6, "", ("192.0.2.9", 0))]

    monkeypatch.setattr(enrollment.socket, "getaddrinfo", getaddrinfo)

    assert resolve_hub_address() == "192.0.2.9"
    assert asked == [
        (
            "hub.neutrino.internal",
            enrollment.socket.AF_INET,
            enrollment.socket.SOCK_STREAM,
        )
    ]


def test_a_lookup_that_fails_resolves_to_nothing(monkeypatch):
    def getaddrinfo(*args):
        raise enrollment.socket.gaierror("no such name")

    monkeypatch.setattr(enrollment.socket, "getaddrinfo", getaddrinfo)

    assert resolve_hub_address() == ""


def test_the_route_to_the_hub_is_read_off_the_first_literal():
    """A loopback address is routed on every machine; a name is skipped."""
    assert default_source_address(["https://hub.lan:8443", "http://127.0.0.1:9"]) == (
        "127.0.0.1"
    )
    assert default_source_address(["https://hub.lan:8443"]) == ""
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


def test_a_link_without_an_overlay_carries_none():
    *_, overlay = parse_link(link_for({"urls": ["http://g"], "token": "t"}))

    assert overlay is None


@pytest.mark.parametrize("material", [NETBIRD, EASYTIER, CONSOLE])
def test_a_link_carries_the_overlay_object(material):
    *_, overlay = parse_link(
        link_for({"urls": ["http://g"], "token": "t", "overlay": material})
    )

    assert overlay == material


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


def test_a_netbird_overlay_may_name_no_management_url_or_fqdn():
    raw = dict(NETBIRD, fqdn="")

    assert enrollment.clean_overlay(raw) == raw


def test_the_join_keeps_the_links_overlay_on_the_binding(monkeypatch):
    def post(self, path, payload):
        return {"id": "c9", "token": "tok9"}

    monkeypatch.setattr(channel.GatewayHttpChannel, "post", post)

    binding = enrollment.enroll(
        link_for({"urls": ["http://g:1"], "token": "t", "overlay": EASYTIER})
    )

    assert binding["overlay"] == EASYTIER
    assert enrollment.bindings()[0]["overlay"] == EASYTIER


def test_note_overlay_writes_and_clears_one_bindings_object():
    enrollment.add_binding(BINDING)
    enrollment.add_binding(SECOND)

    enrollment.note_overlay("c2", NETBIRD)
    assert [binding["overlay"] for binding in enrollment.bindings()] == [
        None,
        NETBIRD,
    ]
    enrollment.note_overlay("c2", None)

    assert enrollment.bindings()[1]["overlay"] is None


def test_a_binding_file_with_an_overlay_is_0600(config_path):
    enrollment.add_binding(dict(BINDING, overlay=NETBIRD))

    assert config_path.stat().st_mode & 0o777 == 0o600

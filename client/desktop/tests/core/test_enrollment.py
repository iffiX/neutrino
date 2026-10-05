"""Enrollment as one person: the link, the join, and the bindings kept.

The payload is compact JSON compressed with zlib in unpadded base64url, so
the link holds no character a shell splits or a URL escapes; a link whose
role is not ``client`` is refused; a join stores a pending binding at once,
with the link's ticket, its first address, every address and its overlays,
and asks no hub; completing it posts the protocol's seven fields, names no
MAC, and puts the hub's id and token in the pending binding's place, with no
ticket; a refusal is typed by the hub's code; the file is written atomically
and 0600 in the person's own configuration directory; a file of the older
single-binding shape reads as no bindings, and a binding without the address
list reads as one with none. The candidates of a connection round, the hub's
name in a stored address's scheme and port, and the notes a session writes
onto its binding are pinned here too, as is the leave told to each address
in turn within its short time. The link's overlay objects are kept on the
binding in the hub's order with only their providers' own fields, one per
provider, an unknown provider dropped; the wish and the pick are kept per
binding.
"""

import base64
import json
import os
import urllib.parse
import zlib

import pytest

import neutrino_client.core.channel as channel
import neutrino_client.core.enrollment as enrollment
import neutrino_client.core.files as files
from neutrino_client import CLIENT_VERSION
from neutrino_client.constants import (
    CLIENT_JOIN_PATH,
    CLIENT_LEAVE_PATH,
    CLIENT_LEAVE_TELL_TIMEOUT_S,
    PROTOCOL,
)
from neutrino_client.core.enrollment import (
    default_source_address,
    parse_link,
    resolve_hub_address,
)
from neutrino_client.exceptions import (
    EnrollmentError,
    GatewayRefused,
    GatewayUnreachable,
)
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

    with pytest.raises(EnrollmentError) as caught:
        parse_link(link_for(body))

    assert caught.value.code == "link_not_for_client"
    assert caught.value.params == {"role": "agent"}


def test_a_link_naming_no_role_is_refused():
    body = {"urls": ["http://gateway"], "token": "t", "kind": "client", "role": ""}

    with pytest.raises(EnrollmentError) as caught:
        parse_link(link_for(body))

    assert caught.value.code == "link_not_for_client"


def test_a_link_that_does_not_inflate_or_parse_is_unreadable():
    body = {"urls": ["http://gateway"], "token": "t", "role": "client"}
    plain = base64.urlsafe_b64encode(json.dumps(body).encode()).decode()
    garbled = base64.urlsafe_b64encode(zlib.compress(b"{not json", 9)).decode()

    for text in (plain, garbled):
        with pytest.raises(EnrollmentError) as caught:
            parse_link("neutrino://enroll/" + text.rstrip("="))
        assert caught.value.code == "link_unreadable"


def test_the_old_short_form_is_unreadable():
    with pytest.raises(EnrollmentError) as caught:
        parse_link("neutrino://enroll/t@192.168.100.1:8443/" + "ab" * 32)

    assert caught.value.code == "link_unreadable"


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


def pending(link=None) -> dict:
    """A join stored from a link, nothing asked of any hub."""
    return enrollment.enroll(
        link
        or link_for(
            {"urls": ["https://hub:8443", "https://10.0.0.1:8443"], "token": "ticket"}
        )
    )


def test_a_join_stores_the_binding_at_once_and_asks_no_hub(monkeypatch):
    posted = answer_with(monkeypatch, reply={"id": "c1", "token": "tok"})
    link = link_for(
        {
            "urls": ["https://hub:8443", "https://10.0.0.1:8443"],
            "token": "ticket",
            "fp": "ab" * 32,
            "overlays": [EASYTIER],
        }
    )

    binding = enrollment.enroll(link)

    assert posted == []
    assert binding["id"].startswith("pending_")
    assert binding == {
        "id": binding["id"],
        "name": enrollment.socket.gethostname(),
        "hub_id": "",
        "hub_name": "",
        "gateway_url": "https://hub:8443",
        "gateway_urls": ["https://hub:8443", "https://10.0.0.1:8443"],
        "fingerprint": "ab" * 32,
        "token": "",
        "ticket": "ticket",
        "is_pending": True,
        "overlays": [EASYTIER],
        "is_overlay_on": False,
        "overlay_pick": "",
    }
    assert enrollment.bindings() == [binding]


def test_the_join_body_is_the_protocols_seven_fields(monkeypatch):
    posted = answer_with(monkeypatch, reply={"id": "c1", "token": "tok"})
    binding = pending()

    completed = enrollment.complete_join(binding, "https://10.0.0.1:8443")

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
    assert completed == dict(
        {
            key: value
            for key, value in binding.items()
            if key not in ("ticket", "is_pending")
        },
        id="c1",
        token="tok",
        gateway_url="https://10.0.0.1:8443",
    )


def test_a_completed_join_takes_the_pending_ones_place(config_path):
    binding = pending()
    enrollment.add_binding(SECOND)
    completed = dict(binding, id="c1", token="tok", is_pending=False, ticket="")

    enrollment.replace_binding(binding["id"], completed)

    assert [held["id"] for held in enrollment.bindings()] == ["c1", "c2"]
    stored = json.loads(config_path.read_text())["bindings"][0]
    assert "ticket" not in stored and "is_pending" not in stored


def test_a_completed_join_of_a_hub_already_held_replaces_it():
    enrollment.add_binding(BINDING)
    binding = pending()

    enrollment.replace_binding(
        binding["id"], dict(binding, id="c1", token="fresh", is_pending=False)
    )

    (held,) = enrollment.bindings()
    assert (held["id"], held["token"]) == ("c1", "fresh")


def test_the_binding_lands_0600_in_the_persons_own_directory(config_path):
    pending()

    assert config_path.is_file()
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
    assert os.path.dirname(source) == str(config_path.parent)
    assert not os.path.exists(source)
    assert sorted(os.listdir(str(config_path.parent))) == ["client.json"]


@pytest.mark.parametrize(
    "error, code, params",
    [
        (
            channel.GatewayRefused("401", code="ticket_spent"),
            "ticket_spent",
            {},
        ),
        (channel.GatewayRefused("401"), "enroll_refused", {}),
        (
            channel.GatewayRefusedDetail(code="role_mismatch", params={"role": "x"}),
            "role_mismatch",
            {"role": "x"},
        ),
        (
            channel.GatewayProtocolRefused(
                code="protocol_too_old", peer=1, hub=2, minimum=2
            ),
            "protocol_too_old",
            {"peer": 1, "hub": 2, "min": 2},
        ),
    ],
)
def test_a_refused_join_is_typed_and_leaves_the_binding_pending(
    monkeypatch, error, code, params
):
    answer_with(monkeypatch, error=error)
    binding = pending()

    with pytest.raises(EnrollmentError) as caught:
        enrollment.complete_join(binding, "https://hub:8443")

    assert (caught.value.code, caught.value.params) == (code, params)
    assert enrollment.bindings() == [binding]


def test_an_address_that_stops_answering_is_no_refusal(monkeypatch):
    answer_with(monkeypatch, error=channel.GatewayUnreachable("down"))

    with pytest.raises(channel.GatewayUnreachable):
        enrollment.complete_join(pending(), "https://hub:8443")


@pytest.mark.parametrize("reply", [{"id": "c1"}, {"token": "tok"}, {}])
def test_a_reply_without_an_id_and_a_token_is_refused(monkeypatch, reply):
    answer_with(monkeypatch, reply=reply)

    with pytest.raises(EnrollmentError) as caught:
        enrollment.complete_join(pending(), "https://hub:8443")

    assert caught.value.code == "enroll_no_token"


def test_a_pending_binding_without_its_ticket_is_not_one(config_path):
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(
            {
                "bindings": [
                    {"id": "p1", "gateway_url": "http://a", "is_pending": True},
                    {
                        "id": "p2",
                        "gateway_url": "http://a",
                        "is_pending": True,
                        "ticket": "t",
                    },
                ]
            }
        )
    )

    assert [held["id"] for held in enrollment.bindings()] == ["p2"]


# --- leaving ---


def test_leave_posts_the_id_and_the_token_and_keeps_the_binding(monkeypatch):
    posted = answer_with(monkeypatch, reply={})
    enrollment.add_binding(BINDING)

    enrollment.leave(BINDING)

    assert posted == [(CLIENT_LEAVE_PATH, {"id": "c1", "token": "tok"})]
    assert enrollment.bindings() == [BINDING]


def test_leave_pins_the_bindings_own_fingerprint_with_the_short_timeout(monkeypatch):
    made = []

    def __init__(self, *, gateway_url, fingerprint="", timeout=0):
        made.append((gateway_url, fingerprint, timeout))
        self._gateway_url = gateway_url
        self._fingerprint = fingerprint

    monkeypatch.setattr(channel.GatewayHttpChannel, "__init__", __init__)
    monkeypatch.setattr(channel.GatewayHttpChannel, "post", lambda self, p, b: {})

    enrollment.leave(dict(SECOND, fingerprint="cd" * 32))

    ((url, fingerprint, timeout),) = made
    assert (url, fingerprint) == ("https://office.lan:8443", "cd" * 32)
    assert 0 < timeout <= CLIENT_LEAVE_TELL_TIMEOUT_S


def test_leave_tries_the_next_address_only_while_none_answers(monkeypatch):
    tried = []

    def post(self, path, payload):
        tried.append(self._gateway_url)
        if self._gateway_url == "https://office.lan:8443":
            raise GatewayUnreachable("cannot reach hub")
        raise GatewayRefused("401")

    monkeypatch.setattr(channel.GatewayHttpChannel, "post", post)
    binding = dict(
        SECOND,
        fingerprint="cd" * 32,
        gateway_urls=["https://10.0.0.1:8443", "https://10.0.0.2:8443"],
    )

    with pytest.raises(GatewayRefused):
        enrollment.leave(binding)

    assert tried == ["https://office.lan:8443", "https://10.0.0.1:8443"]


def test_leave_gives_up_once_its_time_is_spent(monkeypatch):
    tried = []
    clock = iter([0.0, 0.0, CLIENT_LEAVE_TELL_TIMEOUT_S + 1])

    def post(self, path, payload):
        tried.append(self._gateway_url)
        raise GatewayUnreachable("cannot reach hub")

    monkeypatch.setattr(channel.GatewayHttpChannel, "post", post)
    monkeypatch.setattr(enrollment.time, "monotonic", lambda: next(clock))
    binding = dict(SECOND, fingerprint="cd" * 32, gateway_urls=["https://b:8443"])

    with pytest.raises(GatewayUnreachable):
        enrollment.leave(binding)

    assert tried == ["https://office.lan:8443"]


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
    *_, overlays = parse_link(link_for({"urls": ["http://g"], "token": "t"}))

    assert overlays == []


@pytest.mark.parametrize(
    "material",
    [pytest.param(NETBIRD, marks=pytest.mark.feature("netbird")), EASYTIER, CONSOLE],
)
def test_a_link_carries_the_overlay_objects(material):
    *_, overlays = parse_link(
        link_for({"urls": ["http://g"], "token": "t", "overlays": [material]})
    )

    assert overlays == [material]


@pytest.mark.feature("netbird")
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


def test_an_object_of_an_engine_the_tree_lacks_reads_as_none(monkeypatch):
    monkeypatch.setattr(enrollment.edition, "has_feature", lambda name: False)

    assert enrollment.clean_overlay(NETBIRD) is None
    assert enrollment.clean_overlays([NETBIRD, EASYTIER]) == [EASYTIER]


@pytest.mark.feature("netbird")
def test_a_netbird_overlay_may_name_no_management_url_fqdn_or_address():
    raw = dict(NETBIRD, fqdn="", hub_address="")

    assert enrollment.clean_overlay(raw) == raw


def test_the_join_keeps_the_links_overlays_on_the_binding():
    binding = enrollment.enroll(
        link_for({"urls": ["http://g:1"], "token": "t", "overlays": [EASYTIER]})
    )

    assert binding["overlays"] == [EASYTIER]
    assert enrollment.bindings()[0]["overlays"] == [EASYTIER]
    assert binding["is_overlay_on"] is False


@pytest.mark.feature("netbird")
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
                "urls": ["https://192.168.100.1:8443", "https://[2001:db8::1]:8443"],
                "token": "abc123",
                "fp": "AB" * 32,
            }
        )
    )

    assert urls[1] == "https://[2001:db8::1]:8443"
    parts = urllib.parse.urlsplit(urls[1])
    assert (parts.hostname, parts.port) == ("2001:db8::1", 8443)


def test_the_source_address_is_read_off_an_ipv4_literal_only():
    assert default_source_address(["https://[2001:db8::1]:8443"]) == ""

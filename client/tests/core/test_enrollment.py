"""Enrollment as one person: the link, the join, and the bindings kept.

The payload rides base64url so the link holds no character a shell splits
or a URL escapes; a link whose role is not ``client`` is refused; the join
body is the protocol's seven fields and names no MAC; the reply lands as
one binding in a list, written atomically and 0600 in the person's own
configuration directory; a file of the older single-binding shape reads as
no bindings.
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
from neutrino_client.core.enrollment import parse_link
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
    urls, token, fingerprint = parse_link(
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
    urls, token, _ = parse_link(
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
    urls, token, _ = parse_link(payload)
    assert urls == ["http://gateway:8080"]
    assert token == "t"


def test_a_trailing_slash_is_trimmed():
    urls, _, _ = parse_link(link_for({"urls": ["http://gateway:8080/"], "token": "t"}))
    assert urls == ["http://gateway:8080"]


def test_a_link_without_a_fingerprint_carries_an_empty_one():
    _, _, fingerprint = parse_link(
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
        "fingerprint": "ab" * 32,
        "token": "tok",
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


def test_a_binding_keeps_only_its_seven_fields():
    enrollment.add_binding(dict(BINDING, password="never"))  # scan: allow

    assert enrollment.bindings() == [BINDING]


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

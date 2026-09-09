"""Enrollment as one person: the link, the payload, the binding file.

The payload rides base64url so the link holds no character a shell splits
or a URL escapes; a link made for a device agent is refused; the enroll
body names no machine and no MAC; the binding lands 0600 in the person's
own configuration directory.
"""

import base64
import json
import os

import pytest

import neutrino_client.core.channel as channel
import neutrino_client.core.enrollment as enrollment
from neutrino_client import CLIENT_VERSION
from neutrino_client.core.enrollment import EnrollmentError, parse_link
from tests.conftest import link_for


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
    body = {"urls": ["http://gateway"], "token": "t", "fp": "", "kind": "device"}
    encoded = base64.urlsafe_b64encode(json.dumps(body).encode()).decode()

    with pytest.raises(EnrollmentError) as caught:
        parse_link("neutrino://enroll/" + encoded.rstrip("="))

    assert caught.value.code == "link_not_for_client"
    assert caught.value.params == {"kind": "device"}


def test_a_link_naming_no_kind_is_refused():
    body = {"urls": ["http://gateway"], "token": "t"}
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


def test_the_enroll_body_names_the_person_and_no_machine(monkeypatch):
    posted = answer_with(
        monkeypatch, reply={"token": "tok", "client_id": "c1", "hub_version": "0.2.0"}
    )
    link = link_for({"urls": ["https://hub:8443"], "token": "ticket", "fp": "ab" * 32})

    config = enrollment.enroll(link)

    path, payload = posted[0]
    assert path == "/api/client/enroll"
    assert set(payload) == {
        "enrollment_token",
        "hostname",
        "client_version",
        "platform",
    }
    assert payload["enrollment_token"] == "ticket"
    assert payload["client_version"] == CLIENT_VERSION
    assert set(payload["platform"]) == {"os", "family", "arch"}
    assert "mac_addresses" not in payload and "device_id" not in payload
    assert config["gateway_url"] == "https://hub:8443"
    assert config["token"] == "tok"
    assert config["client_id"] == "c1"
    assert config["fingerprint"] == "ab" * 32


def test_the_binding_lands_0600_in_the_persons_own_directory(monkeypatch, config_path):
    answer_with(monkeypatch, reply={"token": "tok", "client_id": "c1"})

    enrollment.enroll(link_for({"urls": ["http://hub"], "token": "ticket"}))

    assert config_path.is_file()
    assert oct(config_path.stat().st_mode & 0o777) == "0o600"
    assert oct(config_path.parent.stat().st_mode & 0o777) == "0o700"
    assert json.loads(config_path.read_text())["token"] == "tok"


def test_a_refused_ticket_is_typed(monkeypatch):
    answer_with(monkeypatch, error=channel.GatewayRefused("401"))

    with pytest.raises(EnrollmentError) as caught:
        enrollment.enroll(link_for({"urls": ["http://hub"], "token": "ticket"}))

    assert caught.value.code == "enroll_refused"
    assert "gateway_url" not in enrollment.load_config()


def test_a_newer_client_is_typed_with_both_versions(monkeypatch):
    answer_with(
        monkeypatch,
        error=channel.GatewayVersionRefused(
            hub_version="0.1.0", client_version="0.2.0"
        ),
    )

    with pytest.raises(EnrollmentError) as caught:
        enrollment.enroll(link_for({"urls": ["http://hub"], "token": "ticket"}))

    assert caught.value.code == "client_newer_than_hub"
    assert caught.value.params == {"hub_version": "0.1.0", "client_version": "0.2.0"}


def test_no_answering_address_is_typed_naming_them_all(monkeypatch):
    answer_with(monkeypatch, error=channel.GatewayUnreachable("down"))

    with pytest.raises(EnrollmentError) as caught:
        enrollment.enroll(
            link_for({"urls": ["http://a", "http://b"], "token": "ticket"})
        )

    assert caught.value.code == "hub_unreachable"
    assert caught.value.params["urls"] == "http://a, http://b"


def test_a_reply_without_a_token_is_refused(monkeypatch):
    answer_with(monkeypatch, reply={"client_id": "c1"})

    with pytest.raises(EnrollmentError) as caught:
        enrollment.enroll(link_for({"urls": ["http://hub"], "token": "ticket"}))

    assert caught.value.code == "enroll_no_token"


def test_disconnect_forgets_the_hub_and_the_stamp_moves(monkeypatch, config_path):
    answer_with(monkeypatch, reply={"token": "tok", "client_id": "c1"})
    enrollment.enroll(link_for({"urls": ["http://hub"], "token": "ticket"}))
    before = enrollment.config_stamp()
    os.utime(str(config_path), (1, 1))

    enrollment.disconnect()

    assert enrollment.is_configured() is False
    assert enrollment.load_config() == {}
    assert enrollment.config_stamp() not in (0, before)

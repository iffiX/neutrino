"""Enrollment link parsing, which is what a person pastes from anywhere.

The payload rides base64url so the link holds no character a shell splits or
a URL escapes; these prove both directions and the refusals.
"""

import base64
import json

import pytest

from neutrino_agent.core.enrollment import EnrollmentError, parse_link


def link_for(payload: dict) -> str:
    encoded = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    return "neutrino://enroll/" + encoded.rstrip("=")


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
    """A hub serves more than one network, and only one of its addresses is
    on the network of the machine being enrolled — which the hub cannot know
    and the person pasting the link should not have to."""
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
    """The whole point of the format: nothing a shell splits."""
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
    "text",
    [
        "",
        "not a link at all",
        "neutrino://enroll/not-base64!!",
        "neutrino://enroll?url=http%3A%2F%2Fold&token=style",
    ],
)
def test_what_is_not_a_link_is_refused(text):
    with pytest.raises(EnrollmentError):
        parse_link(text)


def test_a_payload_missing_its_half_is_refused():
    with pytest.raises(EnrollmentError):
        parse_link(link_for({"urls": ["http://gateway"]}))
    with pytest.raises(EnrollmentError):
        parse_link(link_for({"token": "t"}))


def test_machine_macs_skip_loopback_and_the_unset(tmp_path, monkeypatch):
    import neutrino_agent.core.enrollment as enrollment_module

    (tmp_path / "lo").mkdir()
    (tmp_path / "lo" / "address").write_text("00:00:00:00:00:00\n")
    (tmp_path / "eth0").mkdir()
    (tmp_path / "eth0" / "address").write_text("AA:BB:CC:DD:EE:01\n")
    (tmp_path / "veth9").mkdir()
    monkeypatch.setattr(enrollment_module, "SYS_NET_DIR", str(tmp_path))

    assert enrollment_module.machine_mac_addresses() == ["aa:bb:cc:dd:ee:01"]

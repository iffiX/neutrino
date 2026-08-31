"""Enrollment link parsing, which is what a person types from a phone."""

import pytest

from neutrino_agent.enrollment import EnrollmentError, parse_link


def test_neutrino_scheme_link():
    urls, token = parse_link(
        "neutrino://enroll?url=http%3A%2F%2F192.168.100.1&token=abc123"
    )
    assert urls == ["http://192.168.100.1"]
    assert token == "abc123"


def test_every_address_the_hub_answers_on_is_carried():
    """A hub serves more than one network, and only one of its addresses is
    on the network of the machine being enrolled — which the hub cannot know
    and the person pasting the link should not have to."""
    urls, token = parse_link(
        "neutrino://enroll"
        "?url=http%3A%2F%2F192.168.8.1%3A8080"
        "&url=http%3A%2F%2F10.0.0.1%3A8080"
        "&token=abc123"
    )

    assert urls == ["http://192.168.8.1:8080", "http://10.0.0.1:8080"]
    assert token == "abc123"


def test_plain_http_link_with_fragment():
    urls, token = parse_link("http://192.168.100.1/enroll#abc123")
    assert urls == ["http://192.168.100.1"]
    assert token == "abc123"


def test_trailing_slash_is_trimmed():
    urls, _ = parse_link("neutrino://enroll?url=http%3A%2F%2Fgateway%3A8080%2F&token=t")
    assert urls == ["http://gateway:8080"]


def test_blank_link_says_what_to_do():
    with pytest.raises(EnrollmentError) as caught:
        parse_link("   ")
    assert "Devices page" in str(caught.value)


def test_link_without_token_is_refused():
    with pytest.raises(EnrollmentError):
        parse_link("http://192.168.100.1/enroll")

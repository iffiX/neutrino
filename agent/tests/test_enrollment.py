"""Enrollment link parsing, which is what a person types from a phone."""

import pytest

from neutrino_agent.enrollment import EnrollmentError, parse_link


def test_neutrino_scheme_link():
    url, token = parse_link(
        "neutrino://enroll?url=http%3A%2F%2F192.168.100.1&token=abc123"
    )
    assert url == "http://192.168.100.1"
    assert token == "abc123"


def test_plain_http_link_with_fragment():
    url, token = parse_link("http://192.168.100.1/enroll#abc123")
    assert url == "http://192.168.100.1"
    assert token == "abc123"


def test_trailing_slash_is_trimmed():
    url, _ = parse_link("neutrino://enroll?url=http%3A%2F%2Fgateway%3A8080%2F&token=t")
    assert url == "http://gateway:8080"


def test_blank_link_says_what_to_do():
    with pytest.raises(EnrollmentError) as caught:
        parse_link("   ")
    assert "Devices page" in str(caught.value)


def test_link_without_token_is_refused():
    with pytest.raises(EnrollmentError):
        parse_link("http://192.168.100.1/enroll")

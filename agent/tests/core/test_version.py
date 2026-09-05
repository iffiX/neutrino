"""Ordering release versions: what parses, what refuses to."""

from neutrino_agent.core.version import parse_version


def test_dotted_integers_parse_in_order():
    assert parse_version("0.1.0") == (0, 1, 0)
    assert parse_version("1.10.2") > parse_version("1.9.9")


def test_a_build_suffix_is_ignored():
    assert parse_version("0.1.0+dev") == (0, 1, 0)


def test_unparseable_text_is_none():
    assert parse_version("") is None
    assert parse_version(None) is None
    assert parse_version("wat") is None
    assert parse_version("1.0-rc1") is None
    assert parse_version("1..0") is None

"""Reading what xray printed.

Everything it writes goes to one stream — a banner, the file it read, the
protocols it wants deprecated, and last the reason it refused — so the reason
has to be picked out of a paragraph that is mostly about something else. The
text here is captured from a real refusal on a Debian 12 box, not written from
memory.
"""

from neutrino_hub.modules.xray.output import failure_of, warnings_of

REFUSAL = """/opt/neutrino/bin/xray run -test -config /var/lib/neutrino/generated/\
xray_config.candidate.json exited 23: Xray 26.3.27 (Xray, Penetrates \
Everything.) d2758a0 (go1.26.1 linux/amd64)
A unified platform for anti-censorship.
2026/09/02 05:01:46.768303 [Info] infra/conf/serial: Reading config: \
&{Name:/var/lib/neutrino/generated/xray_config.candidate.json Format:json}
2026/09/02 05:01:46.782804 [Warning] common/errors: The feature Shadowsocks \
(with no Forward Secrecy, etc.) is deprecated, not recommended for using and \
might be removed. Please migrate to VLESS Encryption as soon as possible.
Failed to start: main: failed to create server > core: not all dependencies \
are resolved.."""

ACCEPTED = """Xray 26.3.27 (Xray, Penetrates Everything.) d2758a0 (go1.26.1 linux/amd64)
A unified platform for anti-censorship.
2026/09/02 05:01:46.768303 [Info] infra/conf/serial: Reading config: &{Name:/tmp/c.json Format:json}
Configuration OK."""


def test_the_reason_is_the_last_link_of_the_chain():
    """xray reports where the error passed through as well as what it was:
    `main: failed to create server` is the path, and the last link is the
    thing a person can do something about."""
    assert failure_of(REFUSAL) == "core: not all dependencies are resolved"


def test_the_banner_and_the_file_it_read_are_not_the_reason():
    reason = failure_of(REFUSAL)

    assert "Penetrates Everything" not in reason
    assert "Reading config" not in reason
    assert "2026/09/02" not in reason


def test_a_deprecation_is_not_the_reason_either():
    """It is printed on runs that succeed, so it explains nothing about one
    that did not."""
    assert "Shadowsocks" not in failure_of(REFUSAL)


def test_the_warnings_are_kept_without_their_filing():
    warnings = warnings_of(REFUSAL)

    assert len(warnings) == 1
    assert warnings[0].startswith("The feature Shadowsocks")
    assert "common/errors" not in warnings[0]
    assert "[Warning]" not in warnings[0]


def test_an_accepted_configuration_has_nothing_to_report():
    assert warnings_of(ACCEPTED) == []


def test_output_nobody_recognises_is_still_read_out():
    """An xray that fails in a way this has never seen must not be reported as
    silence."""
    assert failure_of("something nobody has seen before") == (
        "something nobody has seen before"
    )


def test_an_empty_stream_says_so():
    assert failure_of("") == "no reason given"

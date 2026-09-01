"""Reading the dnsmasq log for the dashboard.

dnsmasq writes several lines per lookup into one file — the query, where it
was forwarded, the reply — and its DHCP server writes leases into the same
file. Everything here turns on telling those apart: the dashboard's count was
every line, which answers three to five times over, and the log socket used to
replay the whole file as new arrivals the first time it followed.
"""

import pytest

from neutrino_hub.web.dns_log import DnsLogReader

# One lookup as dnsmasq actually writes it, plus a lease line from its DHCP
# server, which shares the log.
LOOKUP = (
    "Sep  1 12:51:40 dnsmasq[812]: query[A] github.com from 192.168.100.42\n"
    "Sep  1 12:51:40 dnsmasq[812]: forwarded github.com to 127.0.0.1\n"
    "Sep  1 12:51:40 dnsmasq[812]: reply github.com is 203.0.113.4\n"
)
LEASE = (
    "Sep  1 12:51:41 dnsmasq-dhcp[812]: DHCPREQUEST(enp1s0) 192.168.100.42 "
    "52:54:00:aa:bb:cc\n"
)


@pytest.fixture
def log(tmp_path):
    path = tmp_path / "dnsmasq.log"
    path.write_text("")
    return path


def test_one_lookup_counts_once(log):
    log.write_text(LOOKUP)

    assert DnsLogReader(log_path=log).query_count() == 1


def test_a_lease_is_not_a_query(log):
    log.write_text(LOOKUP + LEASE)

    assert DnsLogReader(log_path=log).query_count() == 1


def test_an_empty_log_counts_nothing(log):
    assert DnsLogReader(log_path=log).query_count() == 0


def test_a_log_that_is_not_there_counts_nothing(tmp_path):
    assert DnsLogReader(log_path=tmp_path / "absent.log").query_count() == 0


def test_following_after_a_tail_returns_only_what_arrived(log):
    """The dashboard asks for the backlog and then follows. Without a shared
    position the first follow reads the file from the beginning and the panel
    draws every line twice."""
    log.write_text(LOOKUP)
    reader = DnsLogReader(log_path=log)
    reader.tail()

    assert reader.follow() == []

    with log.open("a") as stream:
        stream.write(
            "Sep  1 12:52:00 dnsmasq[812]: query[A] example.com from 192.168.100.9\n"
        )

    arrived = reader.follow()
    assert [entry.domain for entry in arrived] == ["example.com"]


def test_a_rotated_log_replays_nothing(log):
    """Its own docstring's promise. Reading from zero after a rotation sends
    the whole new file as arrivals."""
    log.write_text(LOOKUP * 20)
    reader = DnsLogReader(log_path=log)
    reader.tail()

    log.write_text("Sep  1 13:00:00 dnsmasq[812]: query[A] a.com from 192.168.100.1\n")

    assert reader.follow() == []


def test_the_tail_is_newest_first(log):
    log.write_text(
        LOOKUP
        + "Sep  1 12:52:00 dnsmasq[812]: query[A] second.com from 192.168.100.9\n"
    )

    assert [entry.domain for entry in DnsLogReader(log_path=log).tail()] == [
        "second.com",
        "github.com",
    ]

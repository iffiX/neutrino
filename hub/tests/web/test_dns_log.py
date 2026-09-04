"""Reading the dnsmasq log for the dashboard.

dnsmasq writes several lines per lookup into one file — the query, where it
was forwarded, the reply — and its DHCP server writes leases into the same
file. Everything here turns on telling those apart: the dashboard's count was
every line, which answers three to five times over, the log socket used to
replay the whole file as new arrivals the first time it followed, and every
row read as pending because the line saying where the name went was dropped.
"""

import pytest

from neutrino_hub.web.dns_log import DnsLogReader

# One lookup as dnsmasq actually writes it, plus a lease line from its DHCP
# server, which shares the log. The router points dnsmasq at xray's resolver,
# so a forwarded lookup on this box names 127.0.0.1#15353.
LOOKUP = (
    "Sep  1 12:51:40 dnsmasq[812]: query[A] github.com from 192.168.100.42\n"
    "Sep  1 12:51:40 dnsmasq[812]: forwarded github.com to 127.0.0.1#15353\n"
    "Sep  1 12:51:40 dnsmasq[812]: reply github.com is 203.0.113.4\n"
)
LEASE = (
    "Sep  1 12:51:41 dnsmasq-dhcp[812]: DHCPREQUEST(enp1s0) 192.168.100.42 "
    "52:54:00:aa:bb:cc\n"
)
DIRECT_LOOKUP = (
    "Sep  1 12:52:10 dnsmasq[812]: query[A] weibo.com from 192.168.100.42\n"
    "Sep  1 12:52:10 dnsmasq[812]: forwarded weibo.com to 223.5.5.5\n"
    "Sep  1 12:52:10 dnsmasq[812]: reply weibo.com is 203.0.113.5\n"
)
CACHED_LOOKUP = (
    "Sep  1 12:53:00 dnsmasq[812]: query[A] github.com from 192.168.100.9\n"
    "Sep  1 12:53:00 dnsmasq[812]: cached github.com is 203.0.113.4\n"
)
CONFIG_LOOKUP = (
    "Sep  1 12:54:00 dnsmasq[812]: query[AAAA] ads.example.com from 192.168.100.9\n"
    "Sep  1 12:54:00 dnsmasq[812]: config ads.example.com is NXDOMAIN\n"
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
        stream.write(DIRECT_LOOKUP)

    arrived = reader.follow()
    assert [entry.domain for entry in arrived] == ["weibo.com"]


def test_a_rotated_log_replays_nothing(log):
    """Its own docstring's promise. Reading from zero after a rotation sends
    the whole new file as arrivals."""
    log.write_text(LOOKUP * 20)
    reader = DnsLogReader(log_path=log)
    reader.tail()

    log.write_text("Sep  1 13:00:00 dnsmasq[812]: query[A] a.com from 192.168.100.1\n")

    assert reader.follow() == []


def test_the_tail_is_newest_first(log):
    log.write_text(LOOKUP + DIRECT_LOOKUP)

    assert [entry.domain for entry in DnsLogReader(log_path=log).tail()] == [
        "weibo.com",
        "github.com",
    ]


def test_a_lookup_sent_to_the_proxy_resolver_is_proxy(log):
    log.write_text(LOOKUP)

    assert DnsLogReader(log_path=log).tail()[0].outbound == "proxy"


def test_a_lookup_sent_anywhere_else_is_direct(log):
    log.write_text(DIRECT_LOOKUP)

    assert DnsLogReader(log_path=log).tail()[0].outbound == "direct"


def test_an_answer_from_the_cache_is_cached(log):
    log.write_text(CACHED_LOOKUP)

    assert DnsLogReader(log_path=log).tail()[0].outbound == "cached"


def test_an_answer_dnsmasq_gave_itself_is_config(log):
    log.write_text(CONFIG_LOOKUP)

    assert DnsLogReader(log_path=log).tail()[0].outbound == "config"


def test_a_repeated_forward_still_makes_one_entry(log):
    """dnsmasq writes a forwarded line per server it tries."""
    log.write_text(
        "Sep  1 12:55:00 dnsmasq[812]: query[A] slow.example from 192.168.100.5\n"
        "Sep  1 12:55:00 dnsmasq[812]: forwarded slow.example to 127.0.0.1#15353\n"
        "Sep  1 12:55:01 dnsmasq[812]: forwarded slow.example to 127.0.0.1#15353\n"
        "Sep  1 12:55:01 dnsmasq[812]: reply slow.example is 203.0.113.7\n"
    )

    entries = DnsLogReader(log_path=log).tail()
    assert [(entry.domain, entry.outbound) for entry in entries] == [
        ("slow.example", "proxy")
    ]


def test_interleaved_lookups_each_get_their_own_answer(log):
    """Two clients resolving at once put the answers out of order behind the
    queries. Each name has to find its own."""
    log.write_text(
        "Sep  1 12:56:00 dnsmasq[812]: query[A] proxied.example from 192.168.100.10\n"
        "Sep  1 12:56:00 dnsmasq[812]: query[A] plain.example from 192.168.100.11\n"
        "Sep  1 12:56:00 dnsmasq[812]: forwarded plain.example to 223.5.5.5\n"
        "Sep  1 12:56:00 dnsmasq[812]: forwarded proxied.example to 127.0.0.1#15353\n"
        "Sep  1 12:56:00 dnsmasq[812]: reply plain.example is 203.0.113.9\n"
        "Sep  1 12:56:00 dnsmasq[812]: reply proxied.example is 203.0.113.8\n"
    )

    entries = DnsLogReader(log_path=log).tail()
    assert [(entry.domain, entry.outbound) for entry in entries] == [
        ("plain.example", "direct"),
        ("proxied.example", "proxy"),
    ]


def test_a_query_read_before_its_answer_pairs_on_the_next_read(log):
    """A read can land between the query and the line saying where it went.
    The entry waits rather than going out as pending for good."""
    log.write_text(LOOKUP)
    reader = DnsLogReader(log_path=log)
    reader.tail()

    with log.open("a") as stream:
        stream.write(
            "Sep  1 12:57:00 dnsmasq[812]: query[A] late.example from 192.168.100.7\n"
        )
    assert reader.follow() == []

    with log.open("a") as stream:
        stream.write(
            "Sep  1 12:57:00 dnsmasq[812]: forwarded late.example to 127.0.0.1#15353\n"
            "Sep  1 12:57:00 dnsmasq[812]: reply late.example is 203.0.113.11\n"
        )

    arrived = reader.follow()
    assert [(entry.domain, entry.outbound) for entry in arrived] == [
        ("late.example", "proxy")
    ]


def test_a_query_that_never_pairs_goes_out_once_unanswered(log):
    """One read of grace, then the entry is sent with no outbound rather than
    being held out of the panel for good."""
    log.write_text(LOOKUP)
    reader = DnsLogReader(log_path=log)
    reader.tail()

    with log.open("a") as stream:
        stream.write(
            "Sep  1 12:58:00 dnsmasq[812]: query[A] lost.example from 192.168.100.7\n"
        )
    assert reader.follow() == []

    with log.open("a") as stream:
        stream.write(LEASE)

    arrived = reader.follow()
    assert [(entry.domain, entry.outbound) for entry in arrived] == [
        ("lost.example", None)
    ]
    assert reader.follow() == []

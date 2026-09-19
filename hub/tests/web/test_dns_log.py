"""Reading the dnsmasq log for the dashboard.

dnsmasq writes several journal records per lookup: the query, where it was
forwarded, the reply. Its DHCP server writes leases into the same journal.
Everything here turns on telling those apart, and on what becomes of a query
whose answer line never arrives. The dashboard's count was every record, which
answers three to five times over; rows read as pending because the line saying
where the name went was dropped; and a row once drawn can never be corrected,
so one that will never pair is dropped instead of drawn.
"""

import json

import pytest

from neutrino_hub.utils.subprocess_run import CommandResult
from neutrino_hub.web import dns_log
from neutrino_hub.web.dns_log import DNSMASQ_UNIT, PENDING_AGE_S, DnsLogReader

# The second every record is stamped at unless a test moves the clock.
DNSMASQ_PID = 271460
BASE_S = 1_725_190_300.0

# One lookup as dnsmasq writes it into the journal, plus a lease line from its
# DHCP server, which shares the unit. The router points dnsmasq at xray's
# resolver, so a forwarded lookup on this box names 127.0.0.1#15353.
LOOKUP = (
    "query[A] github.com from 192.168.100.42",
    "forwarded github.com to 127.0.0.1#15353",
    "reply github.com is 203.0.113.4",
)
LEASE = ("DHCPREQUEST(enp1s0) 192.168.100.42 52:54:00:aa:bb:cc",)
DIRECT_LOOKUP = (
    "query[A] weibo.com from 192.168.100.42",
    "forwarded weibo.com to 223.5.5.5",
    "reply weibo.com is 203.0.113.5",
)
CACHED_LOOKUP = (
    "query[A] github.com from 192.168.100.9",
    "cached github.com is 203.0.113.4",
)
CONFIG_LOOKUP = (
    "query[AAAA] ads.example.com from 192.168.100.9",
    "config ads.example.com is NXDOMAIN",
)


class StubClock:
    """The panel's wall clock, moved by hand."""

    def __init__(self):
        self.now_s = BASE_S

    def __call__(self) -> float:
        return self.now_s


class StubJournal:
    """The unit's journal, answering ``journalctl`` from what a test wrote."""

    def __init__(self):
        self.records: list[dict[str, str]] = []
        self.commands: list[list[str]] = []
        self.is_readable = True

    def write(self, *messages: str, at_s: float = BASE_S) -> None:
        """Append one record per message, stamped at the given second."""
        for message in messages:
            self.records.append(
                {
                    "__CURSOR": f"s=1;i={len(self.records) + 1}",
                    "__REALTIME_TIMESTAMP": str(int(at_s * 1_000_000)),
                    "MESSAGE": f"dnsmasq[{DNSMASQ_PID}]: {message}",
                }
            )

    def run(self, command: list[str], **keywords) -> CommandResult:
        """Answer one journalctl invocation the way the real one would."""
        del keywords
        self.commands.append(command)
        if not self.is_readable:
            return CommandResult(
                command=command,
                exit_code=1,
                stdout="",
                stderr="Failed to add match: Invalid argument",
            )
        return CommandResult(
            command=command,
            exit_code=0,
            stdout="\n".join(json.dumps(record) for record in self._asked_for(command)),
            stderr="",
        )

    def _asked_for(self, command: list[str]) -> list[dict[str, str]]:
        for word in command:
            if word.startswith("--after-cursor="):
                cursors = [record["__CURSOR"] for record in self.records]
                return self.records[cursors.index(word.partition("=")[2]) + 1 :]
        return self.records[-int(command[command.index("-n") + 1]) :]


@pytest.fixture
def journal(monkeypatch):
    stub = StubJournal()
    monkeypatch.setattr(dns_log, "run", stub.run)
    return stub


@pytest.fixture
def clock():
    return StubClock()


@pytest.fixture
def reader(journal, clock):
    del journal
    return DnsLogReader(clock=clock)


def test_one_lookup_counts_once(journal, reader):
    journal.write(*LOOKUP)

    assert reader.query_count() == 1


def test_a_lease_is_not_a_query(journal, reader):
    journal.write(*LOOKUP, *LEASE)

    assert reader.query_count() == 1


def test_an_empty_journal_counts_nothing(reader):
    assert reader.query_count() == 0


def test_a_journal_that_cannot_be_read_counts_nothing(journal, reader):
    """The unit has no journal until dnsmasq has run once."""
    journal.write(*LOOKUP)
    journal.is_readable = False

    assert reader.query_count() == 0


def test_the_tail_reads_the_dnsmasq_unit_as_json(journal, reader):
    journal.write(*LOOKUP)
    reader.tail()

    assert journal.commands[0][:6] == [
        "journalctl",
        "-u",
        DNSMASQ_UNIT,
        "-o",
        "json",
        "--no-pager",
    ]


def test_following_after_a_tail_returns_only_what_arrived(journal, reader):
    """The dashboard asks for the backlog and then follows. Without a shared
    position the first follow reads the window again and the panel draws
    every row twice."""
    journal.write(*LOOKUP)
    reader.tail()

    assert reader.follow() == []

    journal.write(*DIRECT_LOOKUP)

    arrived = reader.follow()
    assert [entry.domain for entry in arrived] == ["weibo.com"]


def test_a_follow_asks_only_past_the_cursor_it_read_to(journal, reader):
    """The cursor is journald's own position, so a follow names it rather
    than reading the window again and filtering."""
    journal.write(*LOOKUP)
    reader.tail()
    reader.follow()

    assert not any(word.startswith("--after-cursor") for word in journal.commands[0])
    assert journal.commands[-1][-1] == (
        f"--after-cursor={journal.records[-1]['__CURSOR']}"
    )


def test_the_tail_is_newest_first(journal, reader):
    journal.write(*LOOKUP, *DIRECT_LOOKUP)

    assert [entry.domain for entry in reader.tail()] == ["weibo.com", "github.com"]


def test_a_lookup_sent_to_the_proxy_resolver_is_proxy(journal, reader):
    journal.write(*LOOKUP)

    assert reader.tail()[0].outbound == "xray"


def test_a_lookup_sent_anywhere_else_is_direct(journal, reader):
    journal.write(*DIRECT_LOOKUP)

    assert reader.tail()[0].outbound == "direct"


def test_an_answer_from_the_cache_is_cached(journal, reader):
    journal.write(*CACHED_LOOKUP)

    assert reader.tail()[0].outbound == "cached"


def test_an_answer_dnsmasq_gave_itself_is_config(journal, reader):
    journal.write(*CONFIG_LOOKUP)

    assert reader.tail()[0].outbound == "config"


def test_a_repeated_forward_still_makes_one_entry(journal, reader):
    """dnsmasq writes a forwarded line per server it tries."""
    journal.write(
        "query[A] slow.example from 192.168.100.5",
        "forwarded slow.example to 127.0.0.1#15353",
        "forwarded slow.example to 127.0.0.1#15353",
        "reply slow.example is 203.0.113.7",
    )

    entries = reader.tail()
    assert [(entry.domain, entry.outbound) for entry in entries] == [
        ("slow.example", "xray")
    ]


def test_interleaved_lookups_each_get_their_own_answer(journal, reader):
    """Two clients resolving at once put the answers out of order behind the
    queries. Each name has to find its own."""
    journal.write(
        "query[A] proxied.example from 192.168.100.10",
        "query[A] plain.example from 192.168.100.11",
        "forwarded plain.example to 223.5.5.5",
        "forwarded proxied.example to 127.0.0.1#15353",
        "reply plain.example is 203.0.113.9",
        "reply proxied.example is 203.0.113.8",
    )

    entries = reader.tail()
    assert [(entry.domain, entry.outbound) for entry in entries] == [
        ("plain.example", "direct"),
        ("proxied.example", "xray"),
    ]


def test_a_reply_answers_a_query_that_was_not_forwarded_again(journal, reader):
    """dnsmasq writes no second forwarded line while an identical query is in
    flight, so the second lookup's only answer line is its reply. It is
    attributed to the resolver the forward for that name went to."""
    journal.write(
        "query[A] rs-ny.example from 192.168.100.5",
        "forwarded rs-ny.example to 127.0.0.1#15353",
        "query[A] rs-ny.example from 192.168.100.6",
        "reply rs-ny.example is 203.0.113.20",
        "reply rs-ny.example is 203.0.113.20",
    )

    entries = reader.tail()
    assert [(entry.client, entry.outbound) for entry in entries] == [
        ("192.168.100.6", "xray"),
        ("192.168.100.5", "xray"),
    ]


def test_a_reverse_lookup_settles_without_an_answer_line(journal, reader):
    """dnsmasq answers a PTR out of bogus-priv and its lease table and writes
    nothing beside it, so a row waiting for one waits for ever."""
    journal.write("query[PTR] 126.110.168.192.in-addr.arpa from 192.168.100.5")

    entries = reader.tail()
    assert [(entry.domain, entry.outbound) for entry in entries] == [
        ("126.110.168.192.in-addr.arpa", "config")
    ]


def test_an_a_and_an_aaaa_of_one_name_take_their_own_answers(journal, reader):
    """NODATA-IPv6 names the AAAA, so the A is still open for the line that
    says where it went. Pairing on the name alone gives one the other's."""
    journal.write(
        "query[A] split.example from 192.168.100.5",
        "query[AAAA] split.example from 192.168.100.6",
        "cached split.example is NODATA-IPv6",
        "forwarded split.example to 127.0.0.1#15353",
        "reply split.example is 203.0.113.30",
    )

    entries = reader.tail()
    assert [(entry.client, entry.outbound) for entry in entries] == [
        ("192.168.100.6", "cached"),
        ("192.168.100.5", "xray"),
    ]


def test_a_query_read_before_its_answer_pairs_on_the_next_read(journal, reader):
    """A read can land between the query and the line saying where it went.
    The entry waits rather than going out as pending for good."""
    journal.write(*LOOKUP)
    reader.tail()

    journal.write("query[A] late.example from 192.168.100.7")
    assert reader.follow() == []

    journal.write(
        "forwarded late.example to 127.0.0.1#15353",
        "reply late.example is 203.0.113.11",
    )

    arrived = reader.follow()
    assert [(entry.domain, entry.outbound) for entry in arrived] == [
        ("late.example", "xray")
    ]


def test_a_query_past_the_age_limit_is_dropped_rather_than_drawn(
    journal, reader, clock
):
    """A row the panel has drawn can never be corrected, so a query whose
    answer line is late enough to be no answer at all is dropped: the lookup
    behind it is not held up, and its own line arriving later pairs nothing."""
    journal.write(*LOOKUP)
    reader.tail()

    journal.write("query[A] lost.example from 192.168.100.7")
    assert reader.follow() == []

    clock.now_s = BASE_S + PENDING_AGE_S + 1
    journal.write(*DIRECT_LOOKUP, at_s=clock.now_s)

    assert [entry.domain for entry in reader.follow()] == ["weibo.com"]

    journal.write("forwarded lost.example to 223.5.5.5", at_s=clock.now_s)
    assert reader.follow() == []

"""Reading xray's log: which lines go on to the journal, and the failed dials in it."""

from neutrino_hub.modules.xray.log_filter import XrayLogFilter, failed_dial

# The line Xray 26.3.27 wrote on the lab hub when the exit's xray was stopped.
REFUSED = (
    "2026/11/06 21:46:43.749276 [Info] [1602768036] app/proxyman/outbound: "
    "app/proxyman/outbound: failed to process outbound traffic > "
    "proxy/shadowsocks: failed to find an available destination > common/retry: "
    "[dial tcp 192.168.122.167:5800: connect: connection refused] > "
    "common/retry: all retry attempts failed"
)
DETOUR = (
    "2026/11/06 21:46:42.745782 [Info] [1602768036] app/dispatcher: Hit route "
    "rule: [rule_balancer] so taking detour [node_d2e74bca] for [tcp:1.1.1.1:53]"
)
WARNING = "2026/11/06 21:40:01.000000 [Warning] core: Xray 26.3.27 started"


def test_a_refused_dial_names_the_address_and_port():
    assert failed_dial(REFUSED) == ("192.168.122.167", 5800)


def test_a_dial_to_an_ipv6_exit_names_it_without_brackets():
    line = REFUSED.replace("192.168.122.167:5800", "[2001:db8::7]:443")

    assert failed_dial(line) == ("2001:db8::7", 443)


def test_a_line_that_is_no_failed_dial_names_nothing():
    assert failed_dial(DETOUR) is None
    assert failed_dial(WARNING) is None


def test_the_filter_keeps_warnings_and_drops_the_info_of_every_connection():
    keeper = XrayLogFilter()

    assert keeper.is_kept(WARNING, now=0.0)
    assert keeper.is_kept("Xray 26.3.27 (Xray, Penetrates Everything.)", now=0.0)
    assert not keeper.is_kept(DETOUR, now=0.0)
    assert not keeper.is_kept(DETOUR.replace("[Info]", "[Debug]"), now=0.0)


def test_the_filter_keeps_a_failed_dial_once_in_ten_seconds_for_each_address():
    keeper = XrayLogFilter()
    other = REFUSED.replace("192.168.122.167", "203.0.113.9")

    assert keeper.is_kept(REFUSED, now=100.0)
    assert not keeper.is_kept(REFUSED, now=105.0)
    assert keeper.is_kept(other, now=105.0)
    assert keeper.is_kept(REFUSED, now=110.0)

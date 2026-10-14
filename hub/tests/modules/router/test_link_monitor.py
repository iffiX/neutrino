"""What the resident router unit watches, and what counts as a change.

Every line `ip monitor` prints is reported, and its end is reported once. The
fingerprint compares the fields the routing state depends on, so the echo of
an idempotent write and a lease renewal read as nothing.
"""

import io
import json
import threading

from neutrino_hub.modules.router import link_monitor
from neutrino_hub.modules.router.link_monitor import RouterLinkMonitor, link_fingerprint


class _Process:
    def __init__(self, text: str):
        self.stdout = io.StringIO(text)
        self.terminated = False

    def poll(self):
        return None

    def terminate(self):
        self.terminated = True


def test_each_line_is_a_change_and_the_end_is_said_once():
    changes = []
    gone = threading.Event()
    process = _Process("2: enp1s0: <UP>\n3: wlp3s0 inet 10.0.0.1/24\n")

    monitor = RouterLinkMonitor(
        on_change=lambda: changes.append(True),
        on_gone=gone.set,
        popen=lambda command, **keywords: process,
    )
    monitor.start()

    assert gone.wait(timeout=2)
    assert changes == [True, True]


def test_stopping_ends_the_monitor():
    process = _Process("")
    monitor = RouterLinkMonitor(
        on_change=lambda: None,
        on_gone=lambda: None,
        popen=lambda command, **keywords: process,
    )
    monitor.start()

    monitor.stop()

    assert process.terminated


class _Kernel:
    """Answers `ip -json` from a table the test edits."""

    def __init__(self):
        self.answers = {
            ("link", "show"): [{"ifname": "enp1s0", "flags": ["UP", "LOWER_UP"]}],
            ("addr", "show"): [
                {
                    "ifname": "enp2s0",
                    "addr_info": [
                        {
                            "family": "inet",
                            "local": "192.168.12.170",
                            "prefixlen": 24,
                            "dynamic": True,
                            "valid_life_time": 3600,
                        },
                        {
                            "family": "inet6",
                            "local": "2001:db8:12::5",
                            "prefixlen": 64,
                            "valid_life_time": 86400,
                        },
                        {
                            "family": "inet6",
                            "local": "2001:db8:12::a7",
                            "prefixlen": 64,
                            "temporary": True,
                        },
                    ],
                }
            ],
            ("route", "show", "default"): [
                {"dev": "enp2s0", "gateway": "192.168.12.1", "metric": 100}
            ],
            ("route", "show", "table", "100"): [
                {"dst": "default", "dev": "lo", "type": "local"}
            ],
            ("rule", "show"): [{"priority": 100, "fwmark": "0x1", "table": "100"}],
        }

    def __call__(self, command, **keywords):
        class Ran:
            is_success = True

        Ran.stdout = json.dumps(self.answers.get(tuple(command[2:]), []))
        return Ran()


def test_a_renewed_lease_is_not_a_change(monkeypatch):
    kernel = _Kernel()
    monkeypatch.setattr(link_monitor, "run", kernel)
    before = link_fingerprint()

    kernel.answers[("addr", "show")][0]["addr_info"][0]["valid_life_time"] = 3599

    assert link_fingerprint() == before


def test_a_port_going_down_is_a_change(monkeypatch):
    kernel = _Kernel()
    monkeypatch.setattr(link_monitor, "run", kernel)
    before = link_fingerprint()

    kernel.answers[("link", "show")][0]["flags"] = ["NO-CARRIER", "UP"]

    assert link_fingerprint() != before


def test_losing_the_policy_rule_is_a_change(monkeypatch):
    """Another program removing it is the one rule change that matters."""
    kernel = _Kernel()
    monkeypatch.setattr(link_monitor, "run", kernel)
    before = link_fingerprint()

    kernel.answers[("rule", "show")] = []

    assert link_fingerprint() != before


def test_a_temporary_address_replaced_inside_its_network_is_not_a_change(
    monkeypatch,
):
    kernel = _Kernel()
    monkeypatch.setattr(link_monitor, "run", kernel)
    before = link_fingerprint()

    kernel.answers[("addr", "show")][0]["addr_info"][2]["local"] = "2001:db8:12::b9"

    assert link_fingerprint() == before


def test_a_new_ipv6_prefix_is_a_change(monkeypatch):
    """An exposed IPv6 segment's rules name the prefix, so the pass that
    follows renders them again."""
    kernel = _Kernel()
    monkeypatch.setattr(link_monitor, "run", kernel)
    before = link_fingerprint()

    for address in kernel.answers[("addr", "show")][0]["addr_info"][1:]:
        address["local"] = address["local"].replace("2001:db8:12::", "2001:db8:99::")

    assert link_fingerprint() != before

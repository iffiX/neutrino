"""Driving one radio's supplicant: a busy radio, an empty first scan, and the
wait for a supplicant that was only asked for.

Every command is answered from a table; nothing here reaches a radio.
"""

import pytest

from neutrino_hub.modules.router import supplicant
from neutrino_hub.modules.router.supplicant import RouterWifiClient

SCAN_TABLE = (
    "bssid / frequency / signal level / flags / ssid\n"
    "aa:bb:cc:dd:ee:01\t2437\t-40\t[WPA2-PSK-CCMP][ESS]\thome\n"
    "aa:bb:cc:dd:ee:02\t5180\t-70\t[WPA2-PSK-CCMP][ESS]\thome\n"
)


class Answered:
    def __init__(self, stdout: str, exit_code: int = 0):
        self.stdout = stdout
        self.stderr = ""
        self.exit_code = exit_code
        self.is_success = exit_code == 0
        self.command = ["wpa_cli"]


class Radio:
    """Answers `wpa_cli` from a script, one answer per call, in order."""

    def __init__(self, answers: dict[str, list]):
        self.answers = answers
        self.asked: list[str] = []

    def __call__(self, command, **keywords):
        verb = command[command.index("-i") + 2]
        self.asked.append(verb)
        queue = self.answers[verb]
        answer = queue.pop(0) if len(queue) > 1 else queue[0]
        return Answered(answer) if isinstance(answer, str) else answer


@pytest.fixture
def no_sleep(monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr(supplicant.time, "sleep", slept.append)
    return slept


def test_a_first_scan_is_asked_for_its_results_until_it_has_them(monkeypatch, no_sleep):
    """A radio that has just started has no previous scan to answer with."""
    radio = Radio({"scan": ["OK"], "scan_results": ["bssid\n", "bssid\n", SCAN_TABLE]})
    monkeypatch.setattr(supplicant, "run", radio)

    found = RouterWifiClient(interface="wlp3s0").scan()

    assert radio.asked == ["scan", "scan_results", "scan_results", "scan_results"]
    assert [entry["ssid"] for entry in found] == ["home"]
    assert found[0]["signal_percent"] == 100


def test_a_radio_already_scanning_is_not_a_failure(monkeypatch, no_sleep):
    radio = Radio({"scan": ["FAIL-BUSY"], "scan_results": [SCAN_TABLE]})
    monkeypatch.setattr(supplicant, "run", radio)

    found = RouterWifiClient(interface="wlp3s0").scan()

    assert [entry["ssid"] for entry in found] == ["home"]


def test_an_empty_table_is_given_up_on_after_the_wait(monkeypatch, no_sleep):
    radio = Radio({"scan": ["OK"], "scan_results": ["bssid\n"]})
    monkeypatch.setattr(supplicant, "run", radio)
    clock = iter(range(0, 100, 5))
    monkeypatch.setattr(supplicant.time, "monotonic", lambda: next(clock))

    assert RouterWifiClient(interface="wlp3s0").scan() == []
    assert radio.asked.count("scan_results") < 6


def test_the_wait_ends_when_the_supplicant_answers(monkeypatch, no_sleep):
    radio = Radio(
        {
            "status": [
                Answered("", exit_code=255),
                Answered("", exit_code=255),
                "wpa_state=SCANNING",
            ]
        }
    )
    monkeypatch.setattr(supplicant, "run", radio)

    RouterWifiClient(interface="wlp3s0").wait_until_reachable()

    assert radio.asked == ["status", "status", "status"]


def test_a_supplicant_that_never_answers_is_a_timeout(monkeypatch, no_sleep):
    radio = Radio({"status": [Answered("", exit_code=255)]})
    monkeypatch.setattr(supplicant, "run", radio)
    clock = iter(range(0, 100, 5))
    monkeypatch.setattr(supplicant.time, "monotonic", lambda: next(clock))

    with pytest.raises(TimeoutError) as caught:
        RouterWifiClient(interface="wlp3s0").wait_until_reachable()
    assert "neutrino_hub_supplicant@wlp3s0.service" in str(caught.value)

"""The traffic history the hub counts itself: each reading's difference added
to the hour, day and month of every interface but loopback, the write every
5 minutes, a restart in the same boot and a reboot, and what is kept."""

import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from neutrino_hub.modules.router import traffic_history
from neutrino_hub.modules.router.traffic_history import (
    RouterTrafficHistory,
    RouterTrafficTotal,
)
from neutrino_hub.system import interface_traffic

START = datetime(2026, 10, 15, 14, 30, 0)
BOOT_TIME = 1760500000.0


class FakeMachine:
    """The counters and the boot time a test sets, read by the history."""

    def __init__(self):
        self.counters: dict = {}
        self.boot = BOOT_TIME

    def read(self) -> dict:
        return dict(self.counters)

    def boot_time(self) -> float:
        return self.boot


@pytest.fixture
def machine(monkeypatch):
    fake = FakeMachine()
    monkeypatch.setattr(traffic_history, "all_interface_counters", fake.read)
    monkeypatch.setattr(
        traffic_history, "psutil", SimpleNamespace(boot_time=fake.boot_time)
    )
    return fake


def _history(tmp_path) -> RouterTrafficHistory:
    return RouterTrafficHistory(path=tmp_path / "traffic_history.json")


def _stored(tmp_path) -> dict:
    return json.loads((tmp_path / "traffic_history.json").read_text())


def test_each_reading_adds_its_difference_to_the_hour_day_and_month(machine, tmp_path):
    history = _history(tmp_path)
    history.load(now=START)
    machine.counters = {"enp2s0": (1000, 500), "wlp3s0": (10, 10)}
    history.count(now=START)
    machine.counters = {"enp2s0": (1600, 700), "wlp3s0": (40, 15)}
    history.count(now=START + timedelta(seconds=1))
    machine.counters = {"enp2s0": (1700, 750), "wlp3s0": (40, 15)}
    history.count(now=START + timedelta(seconds=2))

    assert history.hourly("enp2s0", now=START) == [
        RouterTrafficTotal("2026-10-15 14:00", 700, 250)
    ]
    assert history.daily("enp2s0", now=START) == [
        RouterTrafficTotal("2026-10-15", 700, 250)
    ]
    assert history.monthly("enp2s0", now=START) == [
        RouterTrafficTotal("2026-10", 700, 250)
    ]
    assert history.daily("wlp3s0", now=START) == [
        RouterTrafficTotal("2026-10-15", 30, 5)
    ]


def test_loopback_is_not_counted(machine, tmp_path):
    history = _history(tmp_path)
    history.load(now=START)
    for counters in ((0, 0), (5000, 5000)):
        machine.counters = {
            "lo": counters,
            "lo0": counters,
            "Loopback Pseudo-Interface 1": counters,
        }
        history.count(now=START)
    history.save(now=START)

    assert _stored(tmp_path)["interfaces"] == {}


def test_an_interface_first_seen_adds_nothing_until_its_next_reading(machine, tmp_path):
    history = _history(tmp_path)
    history.load(now=START)
    machine.counters = {"enp2s0": (1000, 500)}
    history.count(now=START)
    machine.counters = {"enp2s0": (1100, 500), "wg0": (900, 900)}
    history.count(now=START)

    assert history.daily("wg0", now=START) == []
    assert history.daily("enp2s0", now=START) == [
        RouterTrafficTotal("2026-10-15", 100, 0)
    ]


def test_a_counter_that_goes_down_is_a_reset_and_is_counted_from(machine, tmp_path):
    history = _history(tmp_path)
    history.load(now=START)
    machine.counters = {"enp2s0": (5000, 5000)}
    history.count(now=START)
    machine.counters = {"enp2s0": (200, 5300)}
    history.count(now=START)
    machine.counters = {"enp2s0": (260, 5310)}
    history.count(now=START)

    assert history.daily("enp2s0", now=START) == [
        RouterTrafficTotal("2026-10-15", 60, 310)
    ]


def test_the_file_is_written_every_5_minutes(machine, tmp_path):
    history = _history(tmp_path)
    history.load(now=START)
    machine.counters = {"enp2s0": (1000, 500)}
    history.count(now=START)
    machine.counters = {"enp2s0": (1500, 600)}
    history.count(now=START + timedelta(seconds=299))

    assert not (tmp_path / "traffic_history.json").exists()

    history.count(now=START + timedelta(seconds=300))

    stored = _stored(tmp_path)
    assert stored["boot_time"] == BOOT_TIME
    assert stored["counters"] == {"enp2s0": [1500, 600]}
    assert stored["interfaces"]["enp2s0"]["days"] == {"2026-10-15": [500, 100]}

    machine.counters = {"enp2s0": (1600, 600)}
    history.count(now=START + timedelta(seconds=599))
    assert _stored(tmp_path)["counters"] == {"enp2s0": [1500, 600]}
    history.count(now=START + timedelta(seconds=600))
    assert _stored(tmp_path)["counters"] == {"enp2s0": [1600, 600]}


def test_a_clock_set_back_writes_at_once(machine, tmp_path):
    history = _history(tmp_path)
    history.load(now=START)
    machine.counters = {"enp2s0": (1000, 500)}
    history.count(now=START - timedelta(hours=1))

    assert _stored(tmp_path)["counters"] == {"enp2s0": [1000, 500]}


def test_nothing_is_written_before_the_file_is_read(machine, tmp_path):
    history = _history(tmp_path)
    machine.counters = {"enp2s0": (1000, 500)}
    history.count(now=START)
    history.count(now=START + timedelta(hours=1))

    assert not (tmp_path / "traffic_history.json").exists()


def test_a_restart_in_the_same_boot_adds_the_difference_from_the_saved_counters(
    machine, tmp_path
):
    before = _history(tmp_path)
    before.load(now=START)
    machine.counters = {"enp2s0": (1000, 500)}
    before.count(now=START)
    machine.counters = {"enp2s0": (1200, 600)}
    before.count(now=START)
    before.save(now=START)

    # The hub is down while the kernel counts on, and the boot time moves by
    # the second Windows' reading of it may.
    machine.counters = {"enp2s0": (5200, 900)}
    machine.boot = BOOT_TIME + 1
    after = _history(tmp_path)
    after.load(now=START)
    after.count(now=START + timedelta(minutes=10))

    assert after.daily("enp2s0", now=START) == [
        RouterTrafficTotal("2026-10-15", 4200, 400)
    ]


def test_after_a_reboot_the_first_reading_is_counted_from(machine, tmp_path):
    before = _history(tmp_path)
    before.load(now=START)
    machine.counters = {"enp2s0": (1000, 500)}
    before.count(now=START)
    machine.counters = {"enp2s0": (1200, 600)}
    before.count(now=START)
    before.save(now=START)

    machine.boot = BOOT_TIME + 3600
    machine.counters = {"enp2s0": (5000, 5000)}
    after = _history(tmp_path)
    after.load(now=START)
    after.count(now=START)
    machine.counters = {"enp2s0": (5010, 5020)}
    after.count(now=START)

    assert after.daily("enp2s0", now=START) == [
        RouterTrafficTotal("2026-10-15", 210, 120)
    ]
    after.save(now=START)
    assert _stored(tmp_path)["boot_time"] == BOOT_TIME + 3600


def test_hours_are_kept_8_days_days_13_months_and_months_10_years(machine, tmp_path):
    (tmp_path / "traffic_history.json").write_text(
        json.dumps(
            {
                "boot_time": BOOT_TIME,
                "counters": {},
                "interfaces": {
                    "enp2s0": {
                        "hours": {
                            "2026-10-07 14:00": [1, 1],
                            "2026-10-07 15:00": [2, 2],
                        },
                        "days": {"2025-09-15": [3, 3], "2025-09-16": [4, 4]},
                        "months": {"2016-10": [5, 5], "2016-11": [6, 6]},
                    },
                    "veth0": {"months": {"2016-01": [7, 7]}},
                },
            }
        )
    )
    history = _history(tmp_path)
    history.load(now=START)
    history.save(now=START)

    assert _stored(tmp_path)["interfaces"] == {
        "enp2s0": {
            "hours": {"2026-10-07 15:00": [2, 2]},
            "days": {"2025-09-16": [4, 4]},
            "months": {"2016-11": [6, 6]},
        }
    }


def test_each_window_reaches_back_its_own_count(machine, tmp_path):
    history = _history(tmp_path)
    history.load(now=START)
    machine.counters = {"enp2s0": (0, 0)}
    history.count(now=START)
    for moment in (
        START - timedelta(hours=24),
        START - timedelta(hours=23),
        START - timedelta(days=7),
        START - timedelta(days=6),
        datetime(2025, 10, 1),
        datetime(2025, 11, 1),
    ):
        received, sent = machine.counters["enp2s0"]
        machine.counters = {"enp2s0": (received + 1, sent)}
        history.count(now=moment)

    hours = history.hourly("enp2s0", hour_count=24, now=START)
    days = history.daily("enp2s0", day_count=7, now=START)
    months = history.monthly("enp2s0", month_count=12, now=START)
    assert hours[0].label == "2026-10-14 15:00"
    assert days[0].label == "2026-10-09"
    assert [month.label for month in months] == ["2025-11", "2026-10"]


def test_an_unreadable_file_starts_empty(machine, tmp_path):
    (tmp_path / "traffic_history.json").write_text("{not json")
    history = _history(tmp_path)
    history.load(now=START)
    machine.counters = {"enp2s0": (1000, 500)}
    history.count(now=START)

    assert history.daily("enp2s0", now=START) == []


def test_a_clean_stop_writes_the_file(machine, tmp_path):
    history = RouterTrafficHistory(
        path=tmp_path / "traffic_history.json", interval_s=3600
    )
    machine.counters = {"enp2s0": (1000, 500)}
    history.start()
    history.stop()

    assert _stored(tmp_path)["boot_time"] == BOOT_TIME


def test_a_stop_without_a_start_leaves_the_file(machine, tmp_path):
    (tmp_path / "traffic_history.json").write_text("kept")
    _history(tmp_path).stop()

    assert (tmp_path / "traffic_history.json").read_text() == "kept"


PROC_NET_DEV = """\
Inter-|   Receive                                                |  Transmit
 face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed
    lo:  {lo}      12    0    0    0     0          0         0  {lo}   12    0    0    0     0       0          0
enp2s0: {received}  120000    0    0    0     0          0         0  {sent}   80000    0    0    0     0       0          0
"""


def test_on_linux_the_counters_come_from_the_kernel_table(
    monkeypatch, tmp_path, machine
):
    monkeypatch.setattr(
        traffic_history,
        "all_interface_counters",
        interface_traffic.all_interface_counters,
    )
    table = tmp_path / "dev"
    monkeypatch.setattr(interface_traffic, "PROC_NET_DEV", table)
    history = _history(tmp_path)
    history.load(now=START)
    for lo, received, sent in ((10, 1000, 500), (99999, 1700, 800)):
        table.write_text(PROC_NET_DEV.format(lo=lo, received=received, sent=sent))
        history.count(now=START)

    assert history.daily("enp2s0", now=START) == [
        RouterTrafficTotal("2026-10-15", 700, 300)
    ]
    assert history.daily("lo", now=START) == []


def test_elsewhere_the_same_count_comes_from_psutil(
    elsewhere, monkeypatch, tmp_path, machine
):
    from tests.conftest import FakePsutil

    monkeypatch.setattr(
        traffic_history,
        "all_interface_counters",
        interface_traffic.all_interface_counters,
    )
    system = FakePsutil()
    monkeypatch.setattr(interface_traffic, "psutil", system)
    loopback = "lo0" if elsewhere == "darwin" else "Loopback Pseudo-Interface 1"
    history = _history(tmp_path)
    history.load(now=START)
    for counters in ((1000, 500), (1700, 800)):
        system.counters = {"Ethernet": counters, loopback: counters}
        history.count(now=START)

    assert history.daily("Ethernet", now=START) == [
        RouterTrafficTotal("2026-10-15", 700, 300)
    ]
    assert history.daily(loopback, now=START) == []

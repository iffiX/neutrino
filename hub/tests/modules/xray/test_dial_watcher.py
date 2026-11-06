"""Following xray's log for failed dials: the child's log file, and the unit's journal."""

import sys
import threading

from neutrino_hub.modules.xray.constants import XRAY_LOG_FOLLOW_COMMAND
from neutrino_hub.modules.xray.dial_watcher import XrayDialWatcher
from tests.modules.xray.test_log_filter import DETOUR, REFUSED


def _wait_for(seen: list, count: int) -> None:
    for _ in range(300):
        if len(seen) >= count:
            return
        threading.Event().wait(0.01)
    raise AssertionError(f"saw {seen}, wanted {count}")


def test_the_journal_is_followed_from_its_end():
    assert XRAY_LOG_FOLLOW_COMMAND == [
        "journalctl",
        "-u",
        "neutrino_hub_xray.service",
        "-f",
        "-n",
        "0",
        "-o",
        "cat",
        "--no-pager",
    ]


def test_a_failed_dial_in_the_followed_output_is_handed_on():
    seen: list = []
    script = (
        f"print({DETOUR!r}); print({REFUSED!r}, flush=True); import time; time.sleep(5)"
    )
    watcher = XrayDialWatcher(
        on_failed_dial=lambda host, port: seen.append((host, port)),
        command=[sys.executable, "-c", script],
    )

    watcher.start()
    try:
        _wait_for(seen, 1)
    finally:
        watcher.stop()

    assert seen == [("192.168.122.167", 5800)]


def test_the_log_file_is_followed_from_its_end_and_across_a_rotation(tmp_path):
    log = tmp_path / "xray.log"
    log.write_text(REFUSED.replace("5800", "1111") + "\n")
    seen: list = []
    watcher = XrayDialWatcher(
        on_failed_dial=lambda host, port: seen.append((host, port)), log_path=log
    )

    watcher.start()
    try:
        threading.Event().wait(0.3)
        with log.open("a") as stream:
            stream.write(DETOUR + "\n" + REFUSED + "\n")
        _wait_for(seen, 1)
        log.rename(tmp_path / "xray.log.1")
        log.write_text(REFUSED.replace("5800", "2222") + "\n")
        _wait_for(seen, 2)
    finally:
        watcher.stop()

    assert seen == [("192.168.122.167", 5800), ("192.168.122.167", 2222)]

"""One account's lock, across threads and processes.

What these pin: two runs for one account never overlap, and the second
waits for the first; two accounts run without waiting on each other; a run
that waits past its bound is ``switch_failed`` saying another run holds the
account; a lock file left behind by a process that was killed blocks no one,
since a held lock ends with its process; and the applier, finding an
account held, reports that refusal and runs nothing as the account.
"""

import functools
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from neutrino_agent.ai_tools import applier as applier_module
from neutrino_agent.ai_tools.account_lock import AiToolsAccountLock
from neutrino_agent.ai_tools.applier import AiToolsApplier
from neutrino_agent.exceptions import ToolSwitchError
from tests.ai_tools.fake_platform import FakeAccountPlatform

AGENT_ROOT = Path(__file__).resolve().parents[2]

# A process that takes one lock, says so, and keeps it until it is killed.
HOLDER = """
import sys, time
from neutrino_agent.ai_tools.account_lock import AiToolsAccountLock
AiToolsAccountLock(path=sys.argv[1], account="ann").acquire()
print("held", flush=True)
time.sleep(60)
"""


def holder(path):
    """A process holding the lock at ``path``, once it has said so."""
    process = subprocess.Popen(
        [sys.executable, "-c", HOLDER, str(path)],
        cwd=AGENT_ROOT,
        stdout=subprocess.PIPE,
        text=True,
    )
    assert process.stdout.readline().strip() == "held"
    return process


def stop(process):
    process.kill()
    process.wait(timeout=10)
    process.stdout.close()


def test_two_runs_for_one_account_never_overlap(tmp_path):
    path = str(tmp_path / ".locks" / "ann")
    spans = []

    def run():
        with AiToolsAccountLock(path=path, account="ann", poll_s=0.01):
            start = time.monotonic()
            time.sleep(0.2)
            spans.append((start, time.monotonic()))

    threads = [threading.Thread(target=run) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    spans.sort()
    assert len(spans) == 3
    assert all(spans[i][1] <= spans[i + 1][0] for i in range(len(spans) - 1))


def test_two_accounts_run_without_waiting_on_each_other(tmp_path):
    with AiToolsAccountLock(path=str(tmp_path / ".locks" / "ann"), account="ann"):
        started = time.monotonic()
        with AiToolsAccountLock(
            path=str(tmp_path / ".locks" / "bob"), account="bob", wait_s=0
        ):
            assert time.monotonic() - started < 0.5


def test_a_run_past_the_wait_says_another_run_holds_the_account(tmp_path):
    path = tmp_path / ".locks" / "ann"
    process = holder(path)
    try:
        with pytest.raises(ToolSwitchError) as caught:
            AiToolsAccountLock(
                path=str(path), account="ann", wait_s=0.3, poll_s=0.05
            ).acquire()
    finally:
        stop(process)

    assert caught.value.code == "switch_failed"
    assert caught.value.params == {
        "account": "ann",
        "detail": "another run holds the account",
    }


def test_a_lock_left_by_a_killed_process_blocks_no_one(tmp_path):
    path = tmp_path / ".locks" / "ann"
    stop(holder(path))
    assert path.is_file()

    with AiToolsAccountLock(path=str(path), account="ann", wait_s=0):
        pass


def test_the_lock_is_taken_again_once_given_back(tmp_path):
    lock = AiToolsAccountLock(path=str(tmp_path / "ann"), account="ann", wait_s=0)
    lock.acquire()
    lock.release()
    lock.release()

    with AiToolsAccountLock(path=str(tmp_path / "ann"), account="ann", wait_s=0):
        pass


def test_the_applier_reports_a_held_account_and_runs_nothing_as_it(
    tmp_path, monkeypatch
):
    binary = tmp_path / "bin" / "cc-switch"
    binary.parent.mkdir()
    binary.write_text("")
    platform = FakeAccountPlatform(root=str(tmp_path / "state"))
    applier = AiToolsApplier(
        platform=platform, log=lambda line: None, binary=str(binary)
    )
    monkeypatch.setattr(
        applier_module,
        "AiToolsAccountLock",
        functools.partial(AiToolsAccountLock, wait_s=0.2, poll_s=0.05),
    )
    process = holder(tmp_path / "state" / "ai_tools" / ".locks" / "ann")
    try:
        applier.apply(
            {
                "is_enabled": True,
                "base_url": "http://192.168.10.1:8317",
                "api_key": "k",  # scan: allow
                "tool_configs": {},
                "accounts": [{"account": "ann"}],
            },
            "h1",
        )
    finally:
        stop(process)

    (entry,) = applier.report()["accounts"]
    assert (entry["state"], entry["code"]) == ("failed", "switch_failed")
    assert entry["params"]["detail"] == "another run holds the account"
    assert platform.runs == []
    assert applier.switched_accounts() == []
    assert os.listdir(tmp_path / "state" / "ai_tools") == [".locks"]

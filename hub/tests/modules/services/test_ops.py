"""Listing what an SMB server exports.

The listings here are what real clients print: this hub's own samba answering
with one share and its IPC$, a server exporting nothing, an SMB1-enabled
server that goes on to list workgroups, and a refusal. Reading the share
names out of them is what makes a declared share's health true or false, so
each shape is pinned rather than assumed.
"""

import subprocess

import pytest

from neutrino_hub.modules.services import ops
from neutrino_hub.modules.services.ops import list_shares, parse_share_names
from neutrino_hub.utils.subprocess_run import CommandResult

# What `smbclient -L 127.0.0.1 -N` prints against this hub's own samba.
HUB_LISTING = """Anonymous login successful

\tSharename       Type      Comment
\t---------       ----      -------
\tshare           Disk      Shared space
\tIPC$            IPC       IPC Service (Neutrino Hub)
SMB1 disabled -- no workgroup available
"""

# A server that exports nothing of its own.
EMPTY_LISTING = """Anonymous login successful

\tSharename       Type      Comment
\t---------       ----      -------
\tIPC$            IPC       IPC Service (nas)
SMB1 disabled -- no workgroup available
"""

# An SMB1-enabled server, whose listing runs on into servers and workgroups.
WORKGROUP_LISTING = """Domain=[WORKGROUP] OS=[Windows 6.1] Server=[Samba 4.9.5]

\tSharename       Type      Comment
\t---------       ----      -------
\tprint$          Disk      Printer Drivers
\tmedia           Disk
\tbackup          Disk      Nightly
\tIPC$            IPC       IPC Service (nas)

\tServer               Comment
\t---------            -------
\tNAS                  Samba 4.9.5

\tWorkgroup            Master
\t---------            -------
\tWORKGROUP            NAS
"""

# What a client prints when nothing is listening where it was pointed.
REFUSAL = """do_connect: Connection to 10.0.0.9 failed (Error NT_STATUS_HOST_UNREACHABLE)
"""

# What a secured server prints when it turns the anonymous session away.
DENIED = """session setup failed: NT_STATUS_ACCESS_DENIED
"""


class RecordingRun:
    """Answers with one result and remembers every command it was given."""

    def __init__(self, result: CommandResult | Exception):
        self._result = result
        self.commands: list[list[str]] = []

    def __call__(self, command, **options) -> CommandResult:
        self.commands.append(command)
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


def succeeded(stdout: str) -> CommandResult:
    return CommandResult(command=["smbclient"], exit_code=0, stdout=stdout, stderr="")


def failed(stderr: str) -> CommandResult:
    return CommandResult(command=["smbclient"], exit_code=1, stdout="", stderr=stderr)


@pytest.fixture
def installed(monkeypatch):
    monkeypatch.setattr(ops, "which", lambda name: f"/usr/bin/{name}")


@pytest.mark.parametrize(
    "listing, names",
    [
        (HUB_LISTING, ["share"]),
        (EMPTY_LISTING, []),
        (WORKGROUP_LISTING, ["media", "backup"]),
        (REFUSAL, []),
        ("", []),
    ],
)
def test_the_share_names_are_read_out_of_each_listing_shape(listing, names):
    assert parse_share_names(listing) == names


def test_administrative_shares_are_never_listed():
    """Anything ending in a dollar is the server's own, not a share."""
    assert parse_share_names(WORKGROUP_LISTING) == ["media", "backup"]
    assert parse_share_names(HUB_LISTING) == ["share"]


def test_the_reading_stops_before_the_servers_and_workgroups():
    """Those tables have the same shape, and none of their rows is a share."""
    assert "NAS" not in parse_share_names(WORKGROUP_LISTING)
    assert "WORKGROUP" not in parse_share_names(WORKGROUP_LISTING)


def test_a_server_that_answers_is_listed_by_its_own_client(monkeypatch, installed):
    recorder = RecordingRun(succeeded(HUB_LISTING))
    monkeypatch.setattr(ops, "run", recorder)

    listing = list_shares("192.168.100.1")

    assert listing.names == ["share"]
    assert listing.error_code is None
    assert recorder.commands == [["smbclient", "-L", "192.168.100.1", "-N"]]


def test_an_empty_anonymous_table_is_a_refused_listing_not_truth(
    monkeypatch, installed
):
    """A secured server answers an anonymous login with an empty table, so
    an empty table is never proof a share is absent."""
    monkeypatch.setattr(ops, "run", RecordingRun(succeeded(EMPTY_LISTING)))

    listing = list_shares("192.168.100.7")

    assert listing.names == []
    assert listing.error_code == "list_refused"


def test_a_denied_anonymous_session_is_a_refused_listing_not_unreachable(
    monkeypatch, installed
):
    monkeypatch.setattr(ops, "run", RecordingRun(failed(DENIED)))

    listing = list_shares("192.168.100.7")

    assert listing.error_code == "list_refused"


def test_a_server_that_does_not_answer_is_a_connect_failure(monkeypatch, installed):
    monkeypatch.setattr(ops, "run", RecordingRun(failed(REFUSAL)))

    listing = list_shares("10.0.0.9")

    assert listing.names == []
    assert listing.error_code == "connect_failed"


def test_a_client_killed_on_the_timeout_is_a_connect_failure(monkeypatch, installed):
    """The 2 s discipline is a belt on smbclient's own longer waits."""
    monkeypatch.setattr(
        ops, "run", RecordingRun(subprocess.TimeoutExpired(["smbclient"], 2))
    )

    listing = list_shares("10.0.0.9")

    assert listing.error_code == "connect_failed"


def test_a_hub_without_the_client_says_so_rather_than_guessing(monkeypatch):
    """smbclient ships with samba, so a hub without that module lacks it."""
    monkeypatch.setattr(ops, "which", lambda name: None)
    recorder = RecordingRun(succeeded(HUB_LISTING))
    monkeypatch.setattr(ops, "run", recorder)

    listing = list_shares("192.168.100.1")

    assert listing.error_code == "tool_missing"
    assert listing.names == []
    assert recorder.commands == []

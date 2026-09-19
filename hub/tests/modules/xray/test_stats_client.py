"""What the hub reads out of a running xray, and what it must never print.

`xray api lso` prints every outbound in full, node passwords and user ids
included. Nothing here may carry that output into a log line or an exception.
"""

import pytest

from neutrino_hub.modules.xray import stats_client
from neutrino_hub.modules.xray.constants import XRAY_BALANCER_TAG
from neutrino_hub.modules.xray.stats_client import XrayStatsClient
from neutrino_hub.utils.subprocess_run import CommandResult

SECRET = "b4d0ff1ce"  # scan: allow

# What `xray api bi` prints on the xray this repo pins. A row is an index, the
# value, and spaces to a fixed width; a row carrying no value is the index by
# itself, which is what made "no override" read as the index. The padding is
# built rather than typed, so trimming whitespace cannot take the case with it.
BALANCER_ROW_WIDTH = 22


def balancer_answer(override: str) -> str:
    """One `xray api bi` answer, padded the way xray pads it.

    Args:
        override: The overridden tag; empty prints the row with no value.

    Returns:
        The whole answer.
    """
    override_row = f"    1   {override}" if override else "    1"
    return (
        "  - Selecting Override:\n"
        + override_row.ljust(BALANCER_ROW_WIDTH)
        + "\n  - Selects:\n"
        + "    1   node_hk1".ljust(BALANCER_ROW_WIDTH)
        + "\n"
    )


class _ScriptedApi:
    """The `xray api` command, answering from what a test wrote down."""

    def __init__(self, *, stdout: str = "", exit_code: int = 0, stderr: str = ""):
        self.commands: list = []
        self._stdout = stdout
        self._exit_code = exit_code
        self._stderr = stderr

    def __call__(self, command, **keywords) -> CommandResult:
        self.commands.append(list(command))
        return CommandResult(
            command=list(command),
            exit_code=self._exit_code,
            stdout=self._stdout,
            stderr=self._stderr,
        )


def install(monkeypatch, **keywords) -> _ScriptedApi:
    """Put a scripted `xray api` behind the client."""
    scripted = _ScriptedApi(**keywords)
    monkeypatch.setattr(stats_client, "run", scripted)
    return scripted


def test_the_rows_these_tests_use_are_the_width_xray_prints():
    """The padding is the whole trap, so it is asserted rather than assumed."""
    rows = [
        line
        for line in balancer_answer("direct").splitlines()
        if not line.lstrip().startswith("- ")
    ]

    assert [len(row) for row in rows] == [BALANCER_ROW_WIDTH, BALANCER_ROW_WIDTH]


def test_the_override_is_read_off_the_row_under_the_label(monkeypatch):
    install(monkeypatch, stdout=balancer_answer("node_hk2"))

    assert XrayStatsClient().override_target() == "node_hk2"


def test_an_outbound_outside_the_selector_is_read_back_the_same(monkeypatch):
    """`direct` is not in the balancer's selector and is still accepted."""
    install(monkeypatch, stdout=balancer_answer("direct"))

    assert XrayStatsClient().override_target() == "direct"


def test_an_xray_holding_no_override_says_so_with_nothing(monkeypatch):
    """The row is then the index and padding. Reading the last field off it
    gives the index, which matches no tag the hub ever chooses: the controller
    would shell out to `bo` every round and every frame would say the exit is
    not pinned."""
    install(monkeypatch, stdout=balancer_answer(""))

    assert XrayStatsClient().override_target() == ""


def test_pinning_an_outbound_names_the_balancer_and_the_tag(monkeypatch):
    scripted = install(monkeypatch)

    XrayStatsClient().set_override("node_hk1")

    assert scripted.commands[0][1:] == [
        "api",
        "bo",
        "--server=127.0.0.1:10085",
        "-b",
        XRAY_BALANCER_TAG,
        "node_hk1",
    ]


def test_clearing_the_override_hands_the_balancer_back_its_choice(monkeypatch):
    scripted = install(monkeypatch)

    XrayStatsClient().clear_override()

    assert scripted.commands[0][-3:] == ["-b", XRAY_BALANCER_TAG, "-r"]


def test_the_outbounds_xray_carries_are_read_by_tag(monkeypatch):
    install(
        monkeypatch,
        stdout=(
            '{"outbounds": ['
            '{"tag": "node_hk1", "settings": {"password": "' + SECRET + '"}},'
            '{"tag": "direct"}]}'
        ),
    )

    assert XrayStatsClient().outbound_tags() == ["node_hk1", "direct"]


def test_an_answer_that_is_a_bare_array_is_read_the_same(monkeypatch):
    install(monkeypatch, stdout='[{"tag": "api_in"}, {"tag": "dns_in"}]')

    assert XrayStatsClient().inbound_tags() == ["api_in", "dns_in"]


def test_a_command_that_failed_is_a_connection_error(monkeypatch):
    install(monkeypatch, exit_code=1, stderr="connection refused")

    with pytest.raises(ConnectionError) as refusal:
        XrayStatsClient().outbound_tags()

    assert "connection refused" in str(refusal.value)


def test_a_failure_never_carries_what_the_command_printed(monkeypatch):
    """`lso` prints the node secrets on standard output, and an exception is
    logged wherever it is caught."""
    install(monkeypatch, exit_code=1, stdout=SECRET, stderr="connection refused")

    with pytest.raises(ConnectionError) as refusal:
        XrayStatsClient().outbound_tags()

    assert SECRET not in str(refusal.value)


def test_an_answer_that_is_not_json_never_carries_itself_into_the_message(
    monkeypatch,
):
    install(monkeypatch, stdout="outbound node_hk1 password " + SECRET)

    with pytest.raises(ConnectionError) as refusal:
        XrayStatsClient().outbound_tags()

    assert SECRET not in str(refusal.value)

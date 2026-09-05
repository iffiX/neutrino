"""``nagent run`` and the root gate over every machine-changing command."""

import neutrino_agent.cli.entry as entry


def test_the_gate_covers_exactly_what_changes_the_machine():
    assert sorted(entry.ROOT_COMMANDS) == ["connect", "disconnect", "run"]


def test_status_is_never_gated():
    assert "status" not in entry.ROOT_COMMANDS

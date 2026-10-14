"""Admission: one number, one range, two refusals with the same params, and
the hello of an agent of 0.5 let in for its own update alone."""

import pytest

from neutrino_hub.modules.channel import admission
from neutrino_hub.modules.channel.admission import admit, is_update_only
from neutrino_hub.modules.channel.constants import PROTOCOL, PROTOCOL_MIN


def test_the_number_this_hub_speaks_is_admitted():
    assert admit(PROTOCOL) is None
    assert admit(PROTOCOL_MIN) is None


def test_the_range_is_closed_at_both_ends(monkeypatch):
    monkeypatch.setattr(admission, "PROTOCOL", 3)
    monkeypatch.setattr(admission, "PROTOCOL_MIN", 2)

    assert admit(2) is None
    assert admit(3) is None
    assert admit(1)["code"] == "protocol_too_old"
    assert admit(4)["code"] == "protocol_too_new"


@pytest.mark.parametrize(
    ("protocol", "code"),
    [(PROTOCOL_MIN - 1, "protocol_too_old"), (PROTOCOL + 1, "protocol_too_new")],
)
def test_a_refusal_names_both_sides_and_the_floor(protocol, code):
    assert admit(protocol) == {
        "code": code,
        "params": {"peer": protocol, "hub": PROTOCOL, "min": PROTOCOL_MIN},
    }


def test_a_missing_number_reads_as_zero_and_is_too_old():
    assert admit(0)["code"] == "protocol_too_old"


@pytest.mark.parametrize("protocol", [1, 2, 3])
def test_a_peer_before_0_6_is_too_old(protocol):
    """0.6.0 speaks 4 and raises the floor to its own number."""
    assert (PROTOCOL, PROTOCOL_MIN) == (4, 4)
    assert admit(protocol)["code"] == "protocol_too_old"


def test_only_an_agent_speaking_the_number_of_0_5_is_let_in_for_its_update():
    assert is_update_only("agent", 3) is True
    assert is_update_only("client", 3) is False
    assert is_update_only("agent", 2) is False
    assert is_update_only("agent", PROTOCOL) is False

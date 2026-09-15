"""Admission: one number, one range, two refusals with the same params."""

import pytest

from neutrino_hub.modules.channel import admission
from neutrino_hub.modules.channel.admission import admit
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

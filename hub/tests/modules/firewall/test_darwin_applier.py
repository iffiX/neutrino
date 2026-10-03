"""macOS's application firewall, with socketfilterfw faked.

What these pin: a program the firewall does not list is added and allowed, a
blocked one is allowed, an allowed one is left alone, and a removal takes
only the programs it names and finds.
"""

import subprocess

import pytest

from neutrino_hub.modules.firewall.darwin_applier import (
    FirewallDarwinApplier,
    listed_programs,
)
from tests.conftest import FakeTools

TOOL = "/usr/libexec/ApplicationFirewall/socketfilterfw"
LISTING = """ALF: total number of apps = 3

1 :  /Applications/Music.app
 \t ( Allow incoming connections )

2 :  /app/bin/xray
 \t ( Block incoming connections )

3 :  /usr/local/bin/nhub
 \t ( Allow incoming connections )
"""


@pytest.fixture
def tools() -> FakeTools:
    held = FakeTools()
    held.answers[(TOOL, "--listapps")] = LISTING
    return held


def test_the_listing_says_which_programs_are_allowed():
    assert listed_programs(LISTING) == {
        "/Applications/Music.app": True,
        "/app/bin/xray": False,
        "/usr/local/bin/nhub": True,
    }


def test_a_missing_program_is_added_and_a_blocked_one_allowed(tools):
    notes = FirewallDarwinApplier(run=tools).apply(
        ["/usr/local/bin/nhub", "/app/bin/xray", "/app/bin/netbird"]
    )

    assert notes == ["firewall allows xray", "firewall allows netbird"]
    assert tools.calls[1:] == [
        [TOOL, "--unblockapp", "/app/bin/xray"],
        [TOOL, "--add", "/app/bin/netbird"],
        [TOOL, "--unblockapp", "/app/bin/netbird"],
    ]


def test_every_program_allowed_already_changes_nothing(tools):
    assert FirewallDarwinApplier(run=tools).apply(["/usr/local/bin/nhub"]) == []
    assert tools.calls == [[TOOL, "--listapps"]]


def test_a_refusal_is_raised(tools):
    tools.failing.add((TOOL, "--add"))

    with pytest.raises(subprocess.CalledProcessError):
        FirewallDarwinApplier(run=tools).apply(["/app/bin/netbird"])


def test_a_removal_takes_only_the_programs_it_finds(tools):
    notes = FirewallDarwinApplier(run=tools).remove(
        ["/usr/local/bin/nhub", "/app/bin/xray", "/app/bin/netbird"]
    )

    assert notes == ["firewall forgot nhub", "firewall forgot xray"]
    assert tools.calls[1:] == [
        [TOOL, "--remove", "/usr/local/bin/nhub"],
        [TOOL, "--remove", "/app/bin/xray"],
    ]

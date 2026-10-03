"""macOS's application firewall and pf anchor, with socketfilterfw and pfctl faked.

What these pin: a program the firewall does not list is added and allowed, a
blocked one is allowed, an allowed one is left alone, and a removal takes
only the programs it names and finds; the anchor's rules are kept under the
state root and loaded into ``com.apple/neutrino_hub`` at every pass, pf is
turned on only when it is off and the rules block something, the kept rules
are loaded again at start, and a flush empties the anchor and forgets them.
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


ANCHOR = "com.apple/neutrino_hub"
BLOCKING = "block drop in quick on { en0 } proto tcp from any to any port 80\n"


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


@pytest.fixture
def pf(tmp_path):
    tools = FakeTools()
    tools.answers[("pfctl", "-s", "info")] = "Status: Disabled\n"
    path = tmp_path / "generated" / "firewall_pf_anchor.conf"
    return tools, path, FirewallDarwinApplier(run=tools, rules_path=path)


def test_the_anchor_is_kept_loaded_and_pf_turned_on(pf):
    tools, path, applier = pf

    notes = applier.load_anchor(BLOCKING)

    assert notes == [f"firewall anchor {ANCHOR} blocks 1 rule"]
    assert path.read_text() == BLOCKING
    assert oct(path.stat().st_mode & 0o777) == "0o600"
    assert tools.calls == [
        ["pfctl", "-a", ANCHOR, "-f", str(path)],
        ["pfctl", "-s", "info"],
        ["pfctl", "-E"],
    ]


def test_the_same_anchor_is_loaded_again_and_says_nothing(pf):
    tools, path, applier = pf
    tools.answers[("pfctl", "-s", "info")] = "Status: Enabled for 0 days\n"
    applier.load_anchor(BLOCKING)
    tools.calls.clear()

    assert applier.load_anchor(BLOCKING) == []
    assert tools.calls == [
        ["pfctl", "-a", ANCHOR, "-f", str(path)],
        ["pfctl", "-s", "info"],
    ]


def test_an_empty_anchor_is_loaded_and_leaves_pf_as_it_is(pf):
    tools, path, applier = pf

    assert applier.load_anchor("") == [f"firewall anchor {ANCHOR} blocks nothing"]
    assert tools.calls == [["pfctl", "-a", ANCHOR, "-f", str(path)]]


def test_a_refused_load_is_raised(pf):
    tools, path, applier = pf
    tools.failing.add(("pfctl", "-a"))

    with pytest.raises(subprocess.CalledProcessError):
        applier.load_anchor(BLOCKING)


def test_the_kept_anchor_is_loaded_again_at_start(pf):
    tools, path, applier = pf
    applier.reload_anchor()
    assert tools.calls == []

    path.parent.mkdir(parents=True)
    path.write_text(BLOCKING)
    applier.reload_anchor()

    assert tools.calls == [
        ["pfctl", "-a", ANCHOR, "-f", str(path)],
        ["pfctl", "-s", "info"],
        ["pfctl", "-E"],
    ]


def test_a_flush_empties_the_anchor_and_forgets_the_rules(pf):
    tools, path, applier = pf
    applier.load_anchor(BLOCKING)
    tools.calls.clear()

    assert applier.flush_anchor() == [f"firewall anchor {ANCHOR} flushed"]
    assert tools.calls == [["pfctl", "-a", ANCHOR, "-F", "all"]]
    assert not path.exists()
    assert applier.flush_anchor() == []

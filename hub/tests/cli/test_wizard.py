"""What a first run is told, and what it becomes.

The screens themselves are not tested here. They are a terminal interface,
they change shape whenever the wording does, and a test that feeds them lines
would be rewritten every time without ever having caught anything; they are
tried by hand. What CI covers is the path automation uses — an answers
document — and the one default whose being wrong would cost somebody their
uplink.
"""

import pytest

from neutrino_hub.cli import wizard
from neutrino_hub.modules.router.link_status import LinkStatus


class StubLinks:
    """Two ports, one of them already carrying the default route."""

    def all_links(self) -> list:
        return [
            LinkStatus(name="enp1s0", is_present=True, is_up=True),
            LinkStatus(name="enp2s0", is_present=True, is_up=True),
        ]

    def gateway_for(self, name: str):
        return "203.0.113.1" if name == "enp2s0" else None

    def default_routes(self) -> list:
        return [{"dev": "enp2s0", "gateway": "203.0.113.1"}]


def test_with_no_default_route_anywhere_the_first_port_is_offered(monkeypatch):
    """A machine that reaches nothing yet still has to be set up."""
    monkeypatch.setattr(wizard, "RouterLinkStatus", _NoRoutes)

    assert wizard._uplink_default(["enp1s0", "enp2s0"]) == 1


class _NoRoutes(StubLinks):
    def default_routes(self) -> list:
        return []


def test_an_answers_document_needs_no_terminal():
    """The path automation takes, and the one CI covers."""
    answers = wizard.from_document(
        {
            "password": "a-long-enough-password",
            "network": {
                "mode": "router",
                "wan": ["enp2s0"],
                "lan": ["enp1s0"],
                "address": "192.168.8.1",
                "prefix_len": 24,
            },
        }
    )

    assert answers.password == "a-long-enough-password"
    assert [i.name for i in answers.network.wan_interfaces] == ["enp2s0"]
    assert [i.name for i in answers.network.lan_interfaces] == ["enp1s0"]


def test_a_misspelled_key_is_refused_rather_than_ignored():
    """`upstream_gatway` quietly meaning "no upstream router" is a week lost."""
    with pytest.raises(wizard.WizardAborted, match="upstream_gatway"):
        wizard.from_document(
            {
                "password": "a-long-enough-password",
                "network": {
                    "mode": "side_gateway",
                    "lan": ["enp1s0"],
                    "upstream_gatway": "192.168.1.1",
                },
            }
        )


@pytest.mark.parametrize("missing", ["password", "network"])
def test_an_incomplete_document_is_refused(missing):
    """`--json` takes a complete document; there is no half-answered install."""
    document = {
        "password": "a-long-enough-password",
        "network": {"mode": "server", "lan": ["enp1s0"]},
    }
    document.pop(missing)

    with pytest.raises(wizard.WizardAborted, match=missing):
        wizard.from_document(document)


def test_a_mode_nobody_has_is_refused():
    with pytest.raises(wizard.WizardAborted, match="teapot"):
        wizard.from_document(
            {"password": "a-long-enough-password", "network": {"mode": "teapot"}}
        )


def test_the_development_root_is_spelled_the_same_in_both_places():
    """`cli/dev_root.py` cannot read the name from the module that uses it.

    That module resolves the five roots as it is imported, which is the very
    thing the flag has to happen before, so the name is written twice. This is
    what holds the two spellings together.
    """
    from neutrino_hub.cli.dev_root import DEV_ROOT_ENV
    from neutrino_hub.utils.constants import UTILS_DEV_ROOT_ENV

    assert DEV_ROOT_ENV == UTILS_DEV_ROOT_ENV


class _AddressedLinks(StubLinks):
    """A port already carrying an address, as a running machine's does."""

    def all_links(self) -> list:
        return [
            LinkStatus(
                name="enp1s0",
                is_present=True,
                is_up=True,
                ipv4_address="192.168.100.1/24",
            )
        ]


def _on_port(monkeypatch, links_class=None):
    """A wizard whose served port already carries an address."""
    monkeypatch.setattr(wizard, "RouterLinkStatus", links_class or _AddressedLinks)
    asked = wizard.SetupWizard(links=_AddressedLinks().all_links())
    asked._mode = "router"
    asked._lan = "enp1s0"
    monkeypatch.setattr("builtins.input", _pressing_enter)
    return asked


def test_a_port_already_running_a_network_keeps_its_address(monkeypatch):
    """Re-running setup on a gateway must not move its own LAN.

    The port carries an address and no default route, so it is somebody's
    network already — every device on it points at this address as its
    gateway, and offering a fresh one takes them all down at the last step.
    """
    asked = _on_port(monkeypatch)

    asked._ask_address()

    assert asked._address == "192.168.100.1"
    assert asked._prefix_len == 24


def test_a_port_whose_address_came_with_a_route_gets_a_fresh_network(monkeypatch):
    """That address is a lease from the router this box is replacing."""
    asked = _on_port(monkeypatch, links_class=_AddressedAndRouted)

    asked._ask_address()

    assert asked._address == "192.168.8.1"


def test_a_port_with_no_address_gets_a_fresh_network(monkeypatch):
    monkeypatch.setattr(wizard, "RouterLinkStatus", _NoRoutes)
    asked = wizard.SetupWizard(links=_NoRoutes().all_links())
    asked._lan = "enp1s0"
    monkeypatch.setattr("builtins.input", _pressing_enter)

    asked._ask_address()

    assert asked._address == "192.168.8.1"


class _AddressedAndRouted(_AddressedLinks):
    """The same port, but its address arrived with a default route."""

    def default_routes(self) -> list:
        return [{"dev": "enp1s0", "gateway": "192.168.100.254"}]


def _pressing_enter(prompt: str = "") -> str:
    """An input() that takes every default."""
    return ""


def test_a_refused_password_asks_again_rather_than_stepping_back(monkeypatch):
    """Returning "not done" used to mean "go back", and a password one
    character short threw the whole wizard to the welcome screen."""
    asked = wizard.SetupWizard(links=[])
    monkeypatch.setattr(wizard, "read_new_password", _refusing)
    monkeypatch.setattr("builtins.input", _pressing_enter)

    assert asked._ask_password() == wizard.WIZARD_AGAIN


def test_an_accepted_password_goes_on(monkeypatch):
    asked = wizard.SetupWizard(links=[])
    monkeypatch.setattr(wizard, "read_new_password", _returning_password)
    monkeypatch.setattr("builtins.input", _pressing_enter)

    assert asked._ask_password() == wizard.WIZARD_NEXT
    assert asked._password == "a-long-enough-password"


def _refusing(**_keywords) -> str:
    raise wizard.PasswordRefused("use at least 8 characters")


def _returning_password(**_keywords) -> str:
    return "a-long-enough-password"


class _TwoUplinks:
    """A cable and a radio both up, as a laptop-shaped gateway is."""

    def all_links(self) -> list:
        return []

    def default_routes(self) -> list:
        # Lowest metric first, which is what the kernel returns and what
        # decides which of the two is actually carrying traffic.
        return [
            {"dev": "wlp3s0", "gateway": "10.0.0.1"},
            {"dev": "enp2s0", "gateway": "203.0.113.1"},
        ]


def test_the_uplink_offered_is_the_one_carrying_traffic_not_the_first_listed(
    monkeypatch,
):
    """Two ports can hold a default route while only one is being used, and
    the kernel has already ranked them; picking by list order ignores that."""
    monkeypatch.setattr(wizard, "RouterLinkStatus", _TwoUplinks)

    assert wizard._uplink_default(["enp1s0", "enp2s0", "wlp3s0"]) == 3


def test_the_served_port_offered_is_one_that_reaches_nothing(monkeypatch):
    """A port with no default route is the one devices are plugged into."""
    monkeypatch.setattr(wizard, "RouterLinkStatus", _TwoUplinks)

    assert wizard._served_default(["enp2s0", "enp1s0"]) == 2


def test_with_every_port_routed_the_first_is_offered(monkeypatch):
    """Nothing to prefer, so nothing is invented."""
    monkeypatch.setattr(wizard, "RouterLinkStatus", _TwoUplinks)

    assert wizard._served_default(["enp2s0", "wlp3s0"]) == 1


def test_b_steps_back_from_a_text_question_too(monkeypatch):
    """It used to be an answer there, and wrote `b` into the address."""
    asked = _on_port(monkeypatch)
    monkeypatch.setattr("builtins.input", _typing("b"))

    assert asked._ask_address() is False
    assert asked._address != "b"


def test_an_address_that_is_not_one_is_refused(monkeypatch):
    """Nothing typed at a prompt reaches `config/` without being read."""
    asked = _on_port(monkeypatch)
    monkeypatch.setattr("builtins.input", _typing("hello", "10.0.0.1", "24"))

    assert asked._ask_address() is True
    assert asked._address == "10.0.0.1"


def test_a_prefix_that_is_not_one_is_refused(monkeypatch):
    asked = _on_port(monkeypatch)
    monkeypatch.setattr("builtins.input", _typing("10.0.0.1", "99", "8"))

    assert asked._ask_address() is True
    assert asked._prefix_len == 8


def test_the_served_port_cannot_be_the_one_already_going_out(monkeypatch):
    """One port cannot be both sides, and the numbering does not re-base."""
    monkeypatch.setattr(wizard, "RouterLinkStatus", StubLinks)
    asked = wizard.SetupWizard(links=StubLinks().all_links())
    monkeypatch.setattr("builtins.input", _typing("2", "1"))

    chosen = asked._choose(
        asked._names,
        default=1,
        prompt="In",
        refused={"enp2s0": "is already the way out."},
    )

    assert asked._names[chosen] == "enp1s0"


def _typing(*answers: str):
    """An input() that gives each answer in turn, then presses Enter."""
    remaining = iter(answers)

    def typed(prompt: str = "") -> str:
        return next(remaining, "")

    return typed


class _OnePort:
    """A machine with a single interface, as a small server is."""

    def all_links(self) -> list:
        return [LinkStatus(name="eth0", is_present=True, is_up=True)]

    def gateway_for(self, name: str):
        return None

    def default_routes(self) -> list:
        return []


def test_a_one_port_machine_is_not_offered_a_mode_needing_two(monkeypatch):
    """Offering router and then refusing it teaches nothing the list could
    have said first."""
    monkeypatch.setattr(wizard, "RouterLinkStatus", _OnePort)

    asked = wizard.SetupWizard(links=_OnePort().all_links())

    assert [mode.key for mode in asked._modes] == [
        "server",
        "one_arm_router",
        "side_gateway",
    ]


def test_a_machine_with_no_interface_cannot_be_set_up(monkeypatch):
    """A gateway with nothing to route on is not a state to configure."""
    monkeypatch.setattr(wizard, "RouterLinkStatus", _NoPorts)

    with pytest.raises(wizard.WizardAborted, match="no network interface"):
        wizard.ask()


class _NoPorts:
    def all_links(self) -> list:
        return []


@pytest.mark.parametrize(
    "mode,expected",
    [
        # Joining somebody's network: the port's own address, always.
        ("server", "192.168.100.1"),
        ("side_gateway", "192.168.100.1"),
        # Becoming the network's gateway: this port already runs one.
        ("router", "192.168.100.1"),
        # A VLAN that does not exist yet, on a trunk whose own address
        # belongs to the untagged traffic this mode sends out.
        ("one_arm_router", "192.168.8.1"),
    ],
)
def test_the_address_offered_says_what_the_mode_is_doing(mode, expected, monkeypatch):
    monkeypatch.setattr(wizard, "RouterLinkStatus", _AddressedLinks)
    asked = wizard.SetupWizard(links=_AddressedLinks().all_links())
    asked._mode = mode
    asked._lan = "enp1s0"

    assert asked._address_default()[0] == expected


def test_a_port_with_nothing_to_keep_offers_nothing_to_a_joining_mode(monkeypatch):
    """There is no guessing somebody else's network; it has to be typed."""
    monkeypatch.setattr(wizard, "RouterLinkStatus", _OnePort)
    asked = wizard.SetupWizard(links=_OnePort().all_links())
    asked._mode = "server"
    asked._lan = "eth0"

    assert asked._address_default()[0] == ""


class _WiredAndRadio:
    """A wired port with a way out, and a radio."""

    def all_links(self) -> list:
        return [
            LinkStatus(name="enp1s0", is_present=True, is_up=True),
            LinkStatus(name="enp2s0", is_present=True, is_up=True),
            LinkStatus(name="wlp3s0", kind="wifi", is_present=True, is_up=True),
        ]

    def gateway_for(self, name: str):
        return "203.0.113.1" if name == "enp2s0" else None

    def default_routes(self) -> list:
        return [{"dev": "enp2s0", "gateway": "203.0.113.1"}]


def test_a_trunk_lists_wires_only(monkeypatch):
    """802.1Q tags do not ride on a radio, and an option nobody may pick is
    noise in a list somebody has to read."""
    monkeypatch.setattr(wizard, "RouterLinkStatus", _WiredAndRadio)
    asked = wizard.SetupWizard(links=_WiredAndRadio().all_links())
    asked._mode = "one_arm_router"

    assert [link.name for link in asked._candidates()] == ["enp1s0", "enp2s0"]


def test_every_other_mode_lists_every_port(monkeypatch):
    monkeypatch.setattr(wizard, "RouterLinkStatus", _WiredAndRadio)
    asked = wizard.SetupWizard(links=_WiredAndRadio().all_links())
    asked._mode = "server"

    assert [link.name for link in asked._candidates()] == [
        "enp1s0",
        "enp2s0",
        "wlp3s0",
    ]


def test_a_radio_is_never_offered_as_a_trunk(monkeypatch):
    """802.1Q tags do not ride on a radio; a mode needing one says so."""
    monkeypatch.setattr(wizard, "RouterLinkStatus", _RadioOnly)
    asked = wizard.SetupWizard(links=_RadioOnly().all_links())

    assert "one_arm_router" not in [mode.key for mode in asked._modes]


class _RadioOnly(_WiredAndRadio):
    def all_links(self) -> list:
        return [LinkStatus(name="wlp3s0", kind="wifi", is_present=True, is_up=True)]

    def default_routes(self) -> list:
        return []


# A share link the parser accepts, made up: example.com, and the password
# inside the base64 is the words "s3cret-password".
SHARE_LINK = (
    "ss://YWVzLTI1Ni1nY206czNjcmV0LXBhc3N3b3Jk@hk.example.com:5800#HK"  # scan: allow
)


def test_a_document_without_a_proxy_skips_it():
    """Leaving it out is what skipping the screen means; a hub is a hub
    without a proxy."""
    answers = wizard.from_document(
        {"password": "a-long-enough-password", "network": {"mode": "server"}}
    )

    assert not answers.proxy.is_enabled
    assert answers.proxy.nodes == ()


def test_a_serving_mode_routes_its_devices_and_publishes_no_socks():
    """Everything the devices send goes through; a SOCKS port is a separate
    ask, and nothing here is worked out from the mode."""
    answers = wizard.from_document(
        {
            "password": "a-long-enough-password",
            "network": {"mode": "router", "wan": ["a"], "lan": ["b"]},
            "proxy": {"links": [SHARE_LINK]},
        }
    )

    assert answers.proxy.is_enabled
    assert not answers.proxy.is_socks_proxy_enabled
    assert not answers.proxy.is_socks_direct_enabled
    assert not answers.proxy.is_local


def test_a_server_has_a_socks_port_for_its_whole_proxy():
    """It diverts nothing, so there is no transparent path to be on."""
    answers = wizard.from_document(
        {
            "password": "a-long-enough-password",
            "network": {"mode": "server", "lan": ["a"], "address": "10.0.0.2"},
            "proxy": {"links": [SHARE_LINK], "socks_proxy_port": 1081},
        }
    )

    assert answers.proxy.is_socks_proxy_enabled
    assert answers.proxy.socks_proxy_port == 1081


def test_this_boxs_own_traffic_is_asked_for_rather_than_assumed():
    """Both readings were defensible, which is why neither is guessed."""
    document = {
        "password": "a-long-enough-password",
        "network": {"mode": "server", "lan": ["a"], "address": "10.0.0.2"},
        "proxy": {"links": [SHARE_LINK]},
    }

    assert not wizard.from_document(document).proxy.is_local
    document["proxy"]["is_local"] = True
    assert wizard.from_document(document).proxy.is_local


def test_a_link_that_cannot_be_read_is_refused():
    with pytest.raises(wizard.WizardAborted):
        wizard.from_document(
            {
                "password": "a-long-enough-password",
                "network": {"mode": "server", "lan": ["a"]},
                "proxy": {"links": ["https://example.com"]},
            }
        )


def test_both_socks_ports_are_asked_for_rather_than_fixed():
    """One was a constant and the other a question, which read as an
    oversight because it was one."""
    answers = wizard.from_document(
        {
            "password": "a-long-enough-password",
            "network": {"mode": "router", "wan": ["a"], "lan": ["b"]},
            "proxy": {
                "links": [SHARE_LINK],
                "is_socks_direct_enabled": True,
                "socks_direct_port": 1088,
            },
        }
    )

    assert answers.proxy.is_socks_direct_enabled
    assert answers.proxy.socks_direct_port == 1088


def test_a_document_can_name_the_modules_to_install():
    """Installing is all it does; each is configured on its own page."""
    answers = wizard.from_document(
        {
            "password": "a-long-enough-password",
            "network": {"mode": "server", "lan": ["a"], "address": "10.0.0.2"},
            "services": ["samba", "podman"],
        }
    )

    assert answers.services == ("samba", "podman")


def test_a_module_nobody_has_is_refused_with_the_ones_there_are():
    with pytest.raises(wizard.WizardAborted, match="postgres"):
        wizard.from_document(
            {
                "password": "a-long-enough-password",
                "network": {"mode": "server", "lan": ["a"]},
                "services": ["postgres"],
            }
        )


def test_naming_no_module_installs_none():
    answers = wizard.from_document(
        {
            "password": "a-long-enough-password",
            "network": {"mode": "server", "lan": ["a"], "address": "10.0.0.2"},
        }
    )

    assert answers.services == ()


def test_core_modules_are_not_offered_as_optional():
    """Setup installs them; offering a choice with one answer is not one."""
    offered = [name for name, _ in wizard._installable()]

    assert "cliproxyapi" not in offered
    assert "samba" in offered

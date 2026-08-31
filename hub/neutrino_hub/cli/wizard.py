"""The questions `nhub setup` asks, on a terminal.

One question per screen, each with a default in brackets that Enter takes, so
an install can be finished without reading. Plain input and print rather than a
curses library: this runs over SSH on a machine that has just been installed,
sometimes on a serial console, and a full-screen interface is the first thing
to break there.

Nothing here writes: it returns what was answered, and `setup` does the work.
"""

import ipaddress
import os
import sys
import textwrap
from dataclasses import dataclass

from neutrino_hub.cli.password import PasswordRefused, read_new_password
from neutrino_hub.modules.router.link_status import RouterLinkStatus
from neutrino_hub.modules.router.modes import (
    ROUTER_MODES_BY_KEY,
    ROUTER_MODE_SERVER,
    ROUTER_MODE_ONE_ARM,
    ROUTER_MODE_BYPASS,
    ROUTER_MODE_DEFAULT_LAN_ADDRESS,
    ROUTER_MODE_DEFAULT_LAN_VLAN,
    ROUTER_MODE_DEFAULT_PREFIX_LEN,
    ROUTER_MODE_ROUTER,
    RouterModePlanner,
    modes_for,
)

# --- config ---
WIZARD_WIDTH = 72
WIZARD_WORDMARK = "NEUTRINO"
WIZARD_LABEL = "Config"
# How far a screen moves the wizard when it is done. Three, not two: a screen
# that could not be answered — a password too short — has to be asked again,
# which is neither going on nor stepping back.
WIZARD_NEXT = 1
WIZARD_AGAIN = 0
WIZARD_PREVIOUS = -1
WIZARD_BACK = "b"
# One per screen, in order. The wordmark repeats; the title does not, because
# the same five words five times teach nobody where they are.
WIZARD_TITLES = (
    "Welcome",
    "A password for the panel",
    "What is this machine for?",
    "Which ports?",
    "Ready",
)
# What the wrapped prose fits inside, leaving room for the indent.
WIZARD_TEXT_WIDTH = 66
WIZARD_ABORTED = "setup was aborted by user, nothing was written"
# What a shell reports for a command somebody interrupted.
WIZARD_STOPPED_STATUS = 130


@dataclass
class WizardAnswers:
    """Everything the wizard asked for, before anything acts on it.

    Attributes:
        password: The panel password, already accepted.
        network: The interface roles the chosen mode describes.
    """

    password: str
    network: object


class WizardAborted(RuntimeError):
    """The wizard cannot go on: a refused answer, or nothing to read from."""


# What an answers document may say, and which planner keyword each becomes.
# Written this way round so a document is checked against one table rather
# than against the shape of a function call.
WIZARD_NETWORK_KEYS = {
    "mode": "mode",
    "wan": "wan_names",
    "lan": "lan_names",
    "trunk": "trunk_name",
    "address": "lan_address",
    "prefix_len": "lan_prefix_len",
    "upstream_gateway": "upstream_gateway",
    "lan_vlan_id": "lan_vlan_id",
}
WIZARD_DOCUMENT_KEYS = ("password", "network")


def from_document(document: dict) -> WizardAnswers:
    """The same answers, read rather than asked for.

    Every key is required to be one this knows: a misspelled
    ``upstream_gatway`` silently becoming "no upstream router" is the kind of
    thing that is found a week after the install.

    Args:
        document: The parsed answers.

    Returns:
        The answers, in the same shape asking produces.

    Raises:
        WizardAborted: On a key this does not know, a missing one, or a mode
            that cannot be planned.
    """
    if not isinstance(document, dict):
        raise WizardAborted("the answers must be an object")
    _reject_unknown(document, WIZARD_DOCUMENT_KEYS, "the answers")
    for required in WIZARD_DOCUMENT_KEYS:
        if required not in document:
            raise WizardAborted(f"the answers need a {required!r}")

    network = document["network"]
    if not isinstance(network, dict):
        raise WizardAborted("'network' must be an object")
    _reject_unknown(network, WIZARD_NETWORK_KEYS, "'network'")
    if "mode" not in network:
        raise WizardAborted("'network' needs a 'mode'")

    keywords = {
        WIZARD_NETWORK_KEYS[key]: _as_tuple(key, value)
        for key, value in network.items()
    }
    try:
        planned = RouterModePlanner(**keywords).plan()
    except (TypeError, ValueError) as error:
        raise WizardAborted(str(error)) from error
    return WizardAnswers(password=document["password"], network=planned)


def _reject_unknown(given: dict, known, what: str) -> None:
    """Refuse a document carrying a key nobody reads.

    Args:
        given: What was parsed.
        known: The keys this accepts.
        what: What to call the object, for the message.

    Raises:
        WizardAborted: On the first key that is not known.
    """
    unknown = sorted(set(given) - set(known))
    if unknown:
        raise WizardAborted(
            f"{what} does not take {', '.join(repr(key) for key in unknown)}; "
            f"it takes {', '.join(sorted(known))}"
        )


def _as_tuple(key: str, value):
    """The port lists as tuples, everything else as given."""
    return tuple(value) if key in ("wan", "lan") else value


class SetupWizard:
    """The questions a first run asks, one screen at a time.

    Every screen clears and redraws, so what is on the terminal is where you
    are rather than everything you have already answered. ``b`` steps back,
    and nothing is written until the last screen is confirmed — which is why
    stepping back costs nothing.

    A terminal this cannot redraw — a pipe, a log — gets the same questions
    printed one after another with no escape sequences in them.
    """

    def __init__(self, *, links: list):
        """
        Args:
            links: The interfaces this machine has, wired first.
        """
        self._step = 1
        self._total = 1
        self._links = links
        self._names = [link.name for link in links]
        self._modes = modes_for(
            len(self._names), sum(1 for link in links if not link.is_wifi)
        )
        self._lan_vlan_id = ROUTER_MODE_DEFAULT_LAN_VLAN
        self._is_coloured = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
        self._password = ""
        self._mode = ROUTER_MODE_ROUTER
        self._wan = ""
        self._lan = ""
        self._address = ROUTER_MODE_DEFAULT_LAN_ADDRESS
        self._prefix_len = ROUTER_MODE_DEFAULT_PREFIX_LEN
        self._upstream = ""

    def run(self) -> WizardAnswers:
        """Ask every screen, and hand back what they answered.

        Returns:
            The answers, for `setup` to act on.

        Raises:
            WizardAborted: On an interrupt, end of input, or a screen that
                cannot be answered.
        """
        screens = (
            self._welcome,
            self._ask_password,
            self._ask_mode,
            self._ask_ports,
            self._review,
        )
        index = 0
        try:
            while index < len(screens):
                self._frame(index + 1, len(screens))
                index = max(0, index + screens[index]())
        except (EOFError, KeyboardInterrupt):
            # SystemExit rather than an exception to propagate: whoever is at
            # the keyboard stopped this, and a traceback would say otherwise.
            print(f"\n\n  {WIZARD_ABORTED}\n", file=sys.stderr)
            raise SystemExit(WIZARD_STOPPED_STATUS) from None
        return WizardAnswers(password=self._password, network=self._plan())

    def _welcome(self) -> bool:
        """What this is, and how long it takes."""
        self._say("One always-on machine, holding your network, your other machines,")
        self._say("your keys, your storage and your services.")
        self._say("")
        self._say("About a minute. Nothing is written until the last screen, and you")
        self._say("can step back at any point.")
        self._prompt("Press Enter to begin")
        return WIZARD_NEXT

    def _ask_password(self) -> bool:
        """The one secret, asked for twice."""
        self._say("Eight characters or more. It is stored as a hash — the panel is")
        self._say("the only thing that uses it.")
        print()
        try:
            self._password = read_new_password()
        except PasswordRefused as error:
            self._say(f"  {error}")
            self._prompt("Press Enter to try again")
            return WIZARD_AGAIN
        return WIZARD_NEXT

    def _ask_mode(self) -> int:
        """Which of the shapes this machine can be."""
        for index, mode in enumerate(self._modes, start=1):
            name = mode.key.replace("_", " ")
            self._say(f"  {index}  {name:<15} {mode.summary}")
        answer = self._choose([mode.key for mode in self._modes], default=1)
        if answer is None:
            return WIZARD_PREVIOUS
        self._mode = self._modes[answer].key
        return WIZARD_NEXT

    def _ask_ports(self) -> int:
        """Which ports the chosen mode uses, and what this box is on them.

        The list is the ports this mode can actually use, numbered from one.
        A mode that needs a trunk lists only wires: 802.1Q tags do not ride on
        a radio, and an option nobody may pick is noise in a list somebody has
        to read.
        """
        caution = ROUTER_MODES_BY_KEY[self._mode].caution
        if caution:
            for line in textwrap.wrap(caution, width=WIZARD_TEXT_WIDTH):
                self._say(f"  {line}")
            self._say("")
        links = self._candidates()
        for index, link in enumerate(links, start=1):
            state = "up" if link.is_up else "down"
            kind = "wifi" if link.is_wifi else "wired"
            here = "  <- the way out today" if _has_route(link.name) else ""
            address = link.ipv4_address or "no address"
            self._say(f"  {index}  {link.name:<10} {kind:<6}{state:<6}{address}{here}")

        names = [link.name for link in links]
        if self._mode == ROUTER_MODE_ROUTER:
            return self._ask_router_ports(names)
        if self._mode == ROUTER_MODE_ONE_ARM:
            return self._ask_one_arm_port(names)
        return self._ask_single_port(names)

    def _candidates(self) -> list:
        """The interfaces the chosen mode can be built on.

        Returns:
            Every interface, or only the wired ones for a mode that needs a
            trunk.
        """
        if ROUTER_MODES_BY_KEY[self._mode].is_wire_needed:
            return [link for link in self._links if not link.is_wifi]
        return self._links

    def _ask_router_ports(self, names: list) -> int:
        """The way out, then the network served, then that network.

        Args:
            names: The ports on offer, as listed.

        Returns:
            How far this screen moves the wizard.
        """
        chosen = self._choose(
            names, default=_uplink_default(names), prompt="Out to the internet"
        )
        if chosen is None:
            return WIZARD_PREVIOUS
        self._wan = names[chosen]

        chosen = self._choose(
            names,
            default=_served_default(names, taken=self._wan),
            prompt="In to your devices",
            refused={self._wan: "is already the way out; pick another port."},
        )
        if chosen is None:
            return WIZARD_PREVIOUS
        self._lan = names[chosen]
        return WIZARD_NEXT if self._ask_address() else WIZARD_PREVIOUS

    def _ask_one_arm_port(self, names: list) -> int:
        """The one wire, the tag carved out of it, then that network.

        Args:
            names: The wired ports on offer, as listed.

        Returns:
            How far this screen moves the wizard.
        """
        chosen = self._choose(
            names,
            default=_uplink_default(names),
            prompt="The one port, out and in",
        )
        if chosen is None:
            return WIZARD_PREVIOUS
        self._wan = ""
        self._lan = names[chosen]
        while True:
            answer = self._text("VLAN tag for your devices", str(self._lan_vlan_id))
            if answer is None:
                return WIZARD_PREVIOUS
            if answer.isdigit() and 1 <= int(answer) <= 4094:
                self._lan_vlan_id = int(answer)
                break
            self._say("  A VLAN tag is a number from 1 to 4094.")
        return WIZARD_NEXT if self._ask_address() else WIZARD_PREVIOUS

    def _ask_single_port(self, names: list) -> int:
        """The one port this box answers on, and its address there.

        Args:
            names: The ports on offer, as listed.

        Returns:
            How far this screen moves the wizard.
        """
        is_bypass = self._mode == ROUTER_MODE_BYPASS
        # A bypass router reaches the world through that network's own router,
        # so the port already carrying a way out is the one; a server routes
        # nothing, and answers where it has an address.
        chosen = self._choose(
            names,
            default=_uplink_default(names) if is_bypass else _served_default(names),
            prompt="Port on that network" if is_bypass else "Port the panel answers on",
        )
        if chosen is None:
            return WIZARD_PREVIOUS
        self._wan = ""
        self._lan = names[chosen]
        if not self._ask_address():
            return WIZARD_PREVIOUS
        if is_bypass:
            while True:
                answer = self._text("That network's own router", _gateway_of(self._lan))
                if answer is None:
                    return WIZARD_PREVIOUS
                if _is_address(answer):
                    self._upstream = answer
                    break
                if not answer:
                    self._say(
                        "  Needed: this box reaches the rest of the world through it."
                    )
                else:
                    self._say(f"  {answer!r} is not an IPv4 address.")
        return WIZARD_NEXT

    def _ask_address(self) -> bool:
        """What this box is on the network reached through the chosen port.

        Always worked out from the port chosen now, never left over from one
        chosen before: showing a port's address beside a different port's name
        is how somebody agrees to a network they never picked.

        Three cases, and the mode names which one applies:

        - **bypass, server** — this box joins a network somebody else runs, so
          it keeps the address that port already has. A port with none has to
          be given one; there is nothing to guess.
        - **router** — this box becomes the network's gateway. A port with an
          address and no default route is already running that network, and
          moving it would take every device on it down; a port whose address
          came with a default route holds a lease from the router being
          replaced, so that address is going away.
        - **one arm router** — the network is a VLAN that does not exist yet.
          The port's own address belongs to its untagged traffic, which is
          this mode's way *out*, so it is never the answer here.

        Returns:
            True when it was answered, False to step back.
        """
        self._address, self._prefix_len = self._address_default()
        while True:
            answer = self._text("This box's address", self._address)
            if answer is None:
                return False
            if _is_address(answer):
                self._address = answer
                break
            if not answer:
                self._say("  Needed: this port has no address to keep.")
            else:
                self._say(f"  {answer!r} is not an IPv4 address.")
        while True:
            answer = self._text("Prefix length", str(self._prefix_len))
            if answer is None:
                return False
            if answer.isdigit() and 1 <= int(answer) <= 32:
                self._prefix_len = int(answer)
                return True
            self._say("  A prefix length is a number from 1 to 32.")

    def _address_default(self) -> tuple:
        """The address and prefix to offer, by what the port is doing.

        Returns:
            The address and prefix length, the address empty where the port
            has none to keep and nothing may be guessed.
        """
        fresh = (ROUTER_MODE_DEFAULT_LAN_ADDRESS, ROUTER_MODE_DEFAULT_PREFIX_LEN)
        if self._mode == ROUTER_MODE_ONE_ARM:
            return fresh
        carried = self._carried_address(self._lan)
        if self._mode in (ROUTER_MODE_BYPASS, ROUTER_MODE_SERVER):
            return carried or ("", ROUTER_MODE_DEFAULT_PREFIX_LEN)
        if carried and self._lan not in _routed_names():
            return carried
        return fresh

    def _carried_address(self, name: str):
        """What address a port has right now.

        Args:
            name: The interface to read.

        Returns:
            Its address and prefix length, or None when it has neither.
        """
        for link in self._links:
            if link.name == name and link.ipv4_address and "/" in link.ipv4_address:
                address, _, prefix = link.ipv4_address.partition("/")
                return address, int(prefix) if prefix.isdigit() else self._prefix_len
        return None

    def _review(self) -> bool:
        """Everything chosen, before anything is written."""
        for interface in self._plan().interfaces:
            line = f"  {interface.name:<14} {interface.role}"
            if interface.is_lan:
                line += f"   {interface.lan.cidr}"
                if interface.lan.is_dhcp_enabled:
                    line += (
                        f"   leases {interface.lan.dhcp_range_start}"
                        f"-{interface.lan.dhcp_range_end}"
                    )
                if interface.lan.upstream_gateway:
                    line += f"   via {interface.lan.upstream_gateway}"
            self._say(line)
        self._say("")
        self._say("This is where the machine changes.")
        if self._prompt("Press Enter to start, b to step back") == WIZARD_BACK:
            return WIZARD_PREVIOUS
        return WIZARD_NEXT

    def _plan(self):
        """The configuration the answers so far describe."""
        return RouterModePlanner(
            mode=self._mode,
            wan_names=(self._wan,) if self._wan else (),
            lan_names=(self._lan,) if self._lan else (),
            trunk_name=self._lan if self._mode == ROUTER_MODE_ONE_ARM else "",
            lan_address=self._address,
            lan_prefix_len=self._prefix_len,
            upstream_gateway=self._upstream or None,
            lan_vlan_id=self._lan_vlan_id,
        ).plan()

    def _frame(self, step: int, total: int) -> None:
        """Clear, then draw the wordmark, the step and what it asks.

        Args:
            step: The one-based screen being drawn.
            total: How many there are.
        """
        print()
        label = f"{WIZARD_LABEL} {step}/{total}"
        dashes = WIZARD_WIDTH - len(WIZARD_WORDMARK) - len(label) - 2
        print()
        print(f"{WIZARD_WORDMARK} {'─' * max(1, dashes)} {label}")
        print()
        print(f"  {WIZARD_TITLES[step - 1]}")
        print()
        self._step = step
        self._total = total

    def _say(self, line: str) -> None:
        """One line of a screen's body."""
        print(f"  {line}" if line else "")

    def _prompt(self, question: str) -> str:
        """Ask one question and read the answer.

        Args:
            question: What to ask.

        Returns:
            What was typed, stripped and lowered.
        """
        print()
        return input(f"  {question}: ").strip().lower()

    def _text(self, question: str, default: str):
        """Ask for a line of text with a default Enter takes.

        Args:
            question: The question.
            default: What Enter takes, shown in brackets when there is one.

        Returns:
            What was typed, the default, or None to step back — because
            ``b`` has to mean the same thing at every prompt, and a wizard
            where it silently became an answer wrote `b` into the address.
        """
        shown = f" [{default}]" if default else ""
        answer = input(f"  {question}{shown}: ").strip()
        if answer.lower() == WIZARD_BACK:
            return None
        return answer or default

    def _choose(
        self, names: list, *, default: int, prompt: str = "Choice", refused: dict = None
    ):
        """Ask for a number in the list just shown, or for a step back.

        Args:
            names: The ports listed, in the order they were numbered.
            default: The one-based choice Enter takes.
            prompt: What to call the question.
            refused: Port names this question may not have, each with why.

        Returns:
            The zero-based choice, or None to step back.
        """
        refused = refused or {}
        while True:
            answer = self._prompt(f"{prompt} [{default}]")
            if answer == WIZARD_BACK:
                return None
            answer = answer or str(default)
            if not (answer.isdigit() and 1 <= int(answer) <= len(names)):
                print(f"  A number from 1 to {len(names)}, or b to step back.")
                continue
            chosen = int(answer) - 1
            reason = refused.get(names[chosen])
            if reason:
                print(f"  {names[chosen]} {reason}")
                continue
            return chosen


def ask() -> WizardAnswers:
    """Ask what this machine is for.

    Returns:
        The answers, for `setup` to act on.

    Raises:
        WizardAborted: When this machine has nothing to configure.
    """
    links = [link for link in RouterLinkStatus().all_links() if link.name != "lo"]
    links.sort(key=_wired_first)
    if not links:
        raise WizardAborted(
            "this machine has no network interface; a gateway needs at least one"
        )
    return SetupWizard(links=links).run()


def _wired_first(link) -> tuple:
    """Sort key putting wired ports above radios, then by name."""
    return (link.is_wifi, link.name)


def _is_address(text: str) -> bool:
    """Whether this is an IPv4 address a network can be built on.

    Args:
        text: What was typed.

    Returns:
        True when the kernel would accept it as a host address.
    """
    try:
        ipaddress.IPv4Address(text)
    except ValueError:
        return False
    return True


def _gateway_of(name: str) -> str:
    """The router this interface reaches the rest of the world through.

    Args:
        name: The interface to read.

    Returns:
        Its default gateway, or an empty string when it has none.
    """
    return RouterLinkStatus().gateway_for(name) or ""


def _has_route(name: str) -> bool:
    """Whether this interface carries a default route today."""
    return bool(RouterLinkStatus().gateway_for(name))


def _uplink_default(names: list) -> int:
    """Which port to offer as the uplink, one-based.

    The port carrying traffic today, which is the one the kernel put first:
    `default_routes` is lowest metric first, and on a box with a cable and a
    radio both up, two ports have a default route while only one is being
    used. Choosing any other is how an install ends with no way out.

    Args:
        names: The interfaces on offer, in the order shown.

    Returns:
        The one-based position to default to.
    """
    for name in _routed_names():
        if name in names:
            return names.index(name) + 1
    return 1


def _routed_names() -> list:
    """Every interface with a default route, the one in use first.

    Returns:
        Interface names, lowest metric first.
    """
    named = []
    for route in RouterLinkStatus().default_routes():
        for entry in [route] + list(route.get("nexthops", [])):
            device = entry.get("dev")
            if device and device not in named:
                named.append(device)
    return named


def _served_default(names: list, *, taken: str = "") -> int:
    """Which port to offer as the served network, one-based.

    A port with no default route is not anybody's way out, which on a gateway
    that is already running is the port that is already the LAN. When every
    port has one, there is nothing to prefer and the first is offered.

    Args:
        names: The interfaces on offer, in the order shown.
        taken: A port already chosen as the way out, which this may not be.

    Returns:
        The one-based position to default to.
    """
    routed = _routed_names()
    for index, name in enumerate(names, start=1):
        if name not in routed and name != taken:
            return index
    for index, name in enumerate(names, start=1):
        if name != taken:
            return index
    return 1


def summarise(answers: WizardAnswers) -> None:
    """Print where the panel will be, once everything is done.

    Args:
        answers: What the wizard collected.
    """
    label = "Done"
    dashes = WIZARD_WIDTH - len(WIZARD_WORDMARK) - len(label) - 2
    print()
    print(f"{WIZARD_WORDMARK} {'─' * max(1, dashes)} {label}")
    print()
    for interface in answers.network.interfaces:
        if interface.is_lan and interface.lan.address:
            print(f"  The panel is at   http://{interface.lan.address}:8080")
            print()
            print("  Proxy nodes, devices, storage and services happen there.")
            break
    print()

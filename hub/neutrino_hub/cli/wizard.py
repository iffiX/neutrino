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
import select
import sys
import textwrap
from pathlib import Path
from dataclasses import dataclass, field

from neutrino_hub.cli.password import read_new_password, worded_refusal
from neutrino_hub.exceptions import PasswordRefusedError, WizardAborted
from neutrino_hub.utils.passwords import (
    PASSWORDS_MASTER_RULES,
    PASSWORDS_PANEL_RULES,
    entropy_bits,
    validate,
)
from neutrino_hub.modules.router.link_status import RouterLinkStatus
from neutrino_hub.modules.xray.constants import XRAY_SOCKS_PORT
from neutrino_hub.modules.xray.node_config import parse_share_link
from neutrino_hub.web.constants import (
    WEB_DEFAULT_LANGUAGE,
    WEB_DEFAULT_LISTEN_PORT,
    WEB_LANGUAGES,
)
from neutrino_hub.utils.constants import UTILS_LOG_DIR
from neutrino_hub.modules.router.modes import (
    ROUTER_MODES_BY_KEY,
    ROUTER_MODE_SERVER,
    ROUTER_LAYOUT_ONE_ARM,
    ROUTER_MODE_SIDE_GATEWAY,
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
    "Language",
    "A password for the panel, and the vault passphrase",
    "What is this machine for?",
    "Which ports?",
    "Going out through a proxy",
    "What else to install on this box",
    "Ready",
)
# The screens that are not questions about the configuration, and so carry no
# counter: the one before the questions asking how they will be answered, the
# one waiting for a browser to take them, and the one after everything.
WIZARD_WELCOME_TITLE = "Welcome"
# Where the run writes itself down, named here so the screen that warns
# about losing the session can say where to read what happened.
SETUP_LOG_PATH = UTILS_LOG_DIR / "setup.log"
WIZARD_DONE_TITLE = "Add your devices"
# How often the last screen looks for a device that has joined.
WIZARD_POLL_INTERVAL_S = 2.0
# What the wrapped prose fits inside, leaving room for the indent.
WIZARD_TEXT_WIDTH = 66
# Said on the router screen, where the wizard takes one port each way and
# the panel takes as many as somebody wants.
WIZARD_ROUTER_NOTE = (
    "Only the primary way out and the primary served network are set here. "
    "The panel's Network page adds more."
)
WIZARD_SERVER_NOTE = (
    "No port is given a job here. Every one of them answers to begin with, "
    "which is what this machine was already doing; the panel's Network page "
    "narrows that."
)
# The languages the panel is drawn in, as the first screen lists them. The
# screen asks in English, whatever it answers.
WIZARD_LANGUAGE_NAMES = {"en": "English", "zh-CN": "Chinese (Simplified)"}
WIZARD_ABORTED = "setup was aborted by user, nothing was written"
# What a shell reports for a command somebody interrupted.
WIZARD_STOPPED_STATUS = 130


@dataclass
class WizardProxy:
    """What the proxy screen answered.

    Every one of these is asked rather than worked out from the mode. What a
    box that routes nothing does with a proxy has no obvious answer, and one
    guessed here is one nobody knows was guessed.

    Attributes:
        is_enabled: Whether traffic goes through an exit node at all.
        nodes: The exit nodes, parsed from the share links pasted in.
        is_local: Whether this box's own traffic goes through as well.
        is_socks_proxy_enabled: Whether a SOCKS port is published whose
            traffic goes through the proxy. It is the whole of the proxy on a
            box that diverts nothing.
        socks_proxy_port: What port that is.
        is_socks_direct_enabled: Whether a SOCKS port is published whose
            traffic deliberately bypasses the proxy.
        socks_direct_port: What port that is.
    """

    is_enabled: bool = False
    nodes: tuple = ()
    is_local: bool = False
    is_socks_proxy_enabled: bool = False
    socks_proxy_port: int = XRAY_SOCKS_PORT
    is_socks_direct_enabled: bool = False
    socks_direct_port: int = XRAY_SOCKS_PORT


@dataclass
class WizardAnswers:
    """Everything the wizard asked for, before anything acts on it.

    Attributes:
        password: The panel password, already accepted.
        vault_passphrase: The vault master passphrase, already accepted.
        network: The interface roles the chosen mode describes.
        proxy: What the proxy screen answered.
        listen_port: The port the panel answers on. Asked whatever shape this
            box is, because every one of them answers somewhere.
        language: The language the panel is drawn in.
    """

    password: str
    network: object
    vault_passphrase: str = ""
    proxy: WizardProxy = field(default_factory=WizardProxy)
    listen_port: int = WEB_DEFAULT_LISTEN_PORT
    language: str = WEB_DEFAULT_LANGUAGE


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
WIZARD_DOCUMENT_KEYS = (
    "password",
    "vault_passphrase",
    "network",
    "proxy",
    "listen_port",
    "language",
)
# A document need not answer the proxy screen; skipping it is what an
# unanswered one means, exactly as it does on the screen.
WIZARD_PROXY_KEYS = (
    "links",
    "is_local",
    "socks_proxy_port",
    "is_socks_direct_enabled",
    "socks_direct_port",
)


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
    for required in ("password", "vault_passphrase", "network"):
        if required not in document:
            raise WizardAborted(f"the answers need a {required!r}")
    _check_secret(document["password"], PASSWORDS_PANEL_RULES, "'password'")
    _check_secret(
        document["vault_passphrase"], PASSWORDS_MASTER_RULES, "'vault_passphrase'"
    )

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
    ports = tuple(link.name for link in RouterLinkStatus().all_links())
    try:
        planned = RouterModePlanner(port_names=ports, **keywords).plan()
    except (TypeError, ValueError) as error:
        raise WizardAborted(str(error)) from error
    return WizardAnswers(
        password=document["password"],
        vault_passphrase=document["vault_passphrase"],
        network=planned,
        proxy=_proxy_from(document.get("proxy", {}), network["mode"]),
        listen_port=_port_from(document.get("listen_port", WEB_DEFAULT_LISTEN_PORT)),
        language=_language_from(document.get("language", WEB_DEFAULT_LANGUAGE)),
    )


def _check_secret(given, rules, what: str) -> None:
    """Judge a document's secret against its rule set.

    Args:
        given: The document's value.
        rules: The rule set to judge by.
        what: What to call the field, for the message.

    Raises:
        WizardAborted: When it is not a string or the rules refuse it.
    """
    if not isinstance(given, str):
        raise WizardAborted(f"{what} must be a string")
    try:
        validate(given, rules)
    except PasswordRefusedError as error:
        raise WizardAborted(f"{what}: {worded_refusal(error)}") from error


def _port_from(given) -> int:
    """The panel's port, read rather than asked for.

    Args:
        given: The document's ``listen_port``.

    Returns:
        The port to serve the panel on.

    Raises:
        WizardAborted: When it is not a port number.
    """
    if isinstance(given, int) and 1 <= given <= 65535:
        return given
    raise WizardAborted(f"{given!r} is not a port number")


def _language_from(given) -> str:
    """The language the panel is drawn in, read rather than asked for.

    Args:
        given: The document's ``language``, ``en`` when it has none.

    Returns:
        The language to draw the panel in.

    Raises:
        WizardAborted: When it is not a language this panel ships.
    """
    if given in WEB_LANGUAGES:
        return str(given)
    raise WizardAborted(
        f"{given!r} is not a language this panel has; "
        f"there is: {', '.join(WEB_LANGUAGES)}"
    )


def _proxy_from(given, mode: str) -> WizardProxy:
    """The proxy screen's answers, read rather than asked for.

    Args:
        given: The document's ``proxy`` object, empty when it has none.
        mode: The network mode, which decides whose traffic goes through.

    Returns:
        What the proxy screen would have collected.

    Raises:
        WizardAborted: On a key this does not know, or a link it cannot read.
    """
    if not isinstance(given, dict):
        raise WizardAborted("'proxy' must be an object")
    _reject_unknown(given, WIZARD_PROXY_KEYS, "'proxy'")
    links = given.get("links", [])
    if not links:
        return WizardProxy()
    try:
        nodes = tuple(parse_share_link(link) for link in links)
    except ValueError as error:
        raise WizardAborted(str(error)) from error
    is_serving = mode != ROUTER_MODE_SERVER
    port = given.get("socks_proxy_port", XRAY_SOCKS_PORT)
    return WizardProxy(
        is_enabled=True,
        nodes=nodes,
        is_local=bool(given.get("is_local", False)),
        # A box that diverts nothing has the SOCKS port as its whole proxy,
        # so naming one is what asking for it means there.
        is_socks_proxy_enabled=not is_serving,
        socks_proxy_port=port,
        is_socks_direct_enabled=bool(given.get("is_socks_direct_enabled", False)),
        socks_direct_port=given.get("socks_direct_port", XRAY_SOCKS_PORT),
    )


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
        self._vault_passphrase = ""
        self._mode = ROUTER_MODE_ROUTER
        self._wan = ""
        self._lan = ""
        self._address = ROUTER_MODE_DEFAULT_LAN_ADDRESS
        self._prefix_len = ROUTER_MODE_DEFAULT_PREFIX_LEN
        self._upstream = ""
        self._proxy = WizardProxy()
        self._listen_port = WEB_DEFAULT_LISTEN_PORT
        self._language = WEB_DEFAULT_LANGUAGE

    def run(self) -> WizardAnswers:
        """Ask every screen, and hand back what they answered.

        Returns:
            The answers, for `setup` to act on.

        Raises:
            WizardAborted: On a screen that cannot be answered.
            SystemExit: When the person interrupts or standard input ends.
        """
        screens = (
            self._ask_language,
            self._ask_password,
            self._ask_mode,
            self._ask_ports,
            self._ask_proxy,
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
        return WizardAnswers(
            password=self._password,
            vault_passphrase=self._vault_passphrase,
            network=self._plan(),
            proxy=self._proxy,
            listen_port=self._listen_port,
            language=self._language,
        )

    def _ask_language(self) -> int:
        """Which language the panel is drawn in; `nhub` itself stays English."""
        codes = list(WEB_LANGUAGES)
        for index, code in enumerate(codes, start=1):
            self._say(f"  {index}  {code:<8}{WIZARD_LANGUAGE_NAMES[code]}")
        answer = self._choose(codes, default=codes.index(self._language) + 1)
        if answer is None:
            return WIZARD_PREVIOUS
        self._language = codes[answer]
        return WIZARD_NEXT

    def _ask_password(self) -> bool:
        """The two secrets, each asked for twice."""
        self._say(
            f"At least {PASSWORDS_PANEL_RULES.min_length} characters, and "
            "better for mixing letters,"
        )
        self._say("numbers and symbols.")
        print()
        try:
            self._password = read_new_password()
            self._say_entropy(self._password)
            print()
            self._say("The vault passphrase seals every stored credential, and a")
            self._say("backup only opens with it.")
            self._say(
                f"At least {PASSWORDS_MASTER_RULES.min_length} characters, with "
                "a lowercase, an uppercase,"
            )
            self._say("a digit and a symbol.")
            print()
            self._vault_passphrase = read_new_password(
                prompt="Vault passphrase", rules=PASSWORDS_MASTER_RULES
            )
            self._say_entropy(self._vault_passphrase)
        except ValueError as error:
            self._say(f"  {error}")
            self._prompt("Press Enter to try again")
            return WIZARD_AGAIN
        return WIZARD_NEXT

    def _say_entropy(self, secret: str) -> None:
        """One line saying how hard what was just accepted is to guess."""
        self._say(f"  entropy: {entropy_bits(secret):.0f} bits")

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
        note = ROUTER_MODES_BY_KEY[self._mode].caution
        if self._mode == ROUTER_MODE_ROUTER:
            note = WIZARD_ROUTER_NOTE
        if self._mode == ROUTER_MODE_SERVER:
            note = WIZARD_SERVER_NOTE
        if note:
            for line in textwrap.wrap(note, width=WIZARD_TEXT_WIDTH):
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
            moved = self._ask_router_ports(names)
        elif self._mode == ROUTER_LAYOUT_ONE_ARM:
            moved = self._ask_one_arm_port(names)
        elif self._mode == ROUTER_MODE_SIDE_GATEWAY:
            moved = self._ask_side_gateway_port(names)
        else:
            # A server gives no port a job. Every one of them answers to
            # begin with, which is what the machine was already doing.
            moved = WIZARD_NEXT
        if moved != WIZARD_NEXT:
            return moved
        # Asked on every path, because every shape of this box answers on a
        # port, and the one it answers on is the address somebody types next.
        port = self._port("Panel answers on port", self._listen_port)
        if port is None:
            return WIZARD_PREVIOUS
        self._listen_port = port
        return WIZARD_NEXT

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

    def _ask_side_gateway_port(self, names: list) -> int:
        """The port on the network this box joins, and that network's router.

        Args:
            names: The ports on offer, as listed.

        Returns:
            How far this screen moves the wizard.
        """
        # It reaches the world through that network's own router, so the port
        # already carrying a way out is the one.
        chosen = self._choose(
            names, default=_uplink_default(names), prompt="Port on that network"
        )
        if chosen is None:
            return WIZARD_PREVIOUS
        self._wan = ""
        self._lan = names[chosen]
        if not self._ask_address():
            return WIZARD_PREVIOUS
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

        - **side gateway** — this box joins a network somebody else runs, so
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
        if self._mode == ROUTER_LAYOUT_ONE_ARM:
            return fresh
        carried = self._carried_address(self._lan)
        if self._mode == ROUTER_MODE_SIDE_GATEWAY:
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

    def _ask_proxy(self) -> int:
        """Whether traffic leaves through an exit node, and through which.

        Skipping is a first-class answer: a hub is a hub without a proxy, and
        the Proxy page turns one on later without any of this being redone.
        """
        is_serving = self._mode != ROUTER_MODE_SERVER
        whose = "your devices' traffic" if is_serving else "this box's own traffic"
        self._say(f"Send {whose} out through an exit node you own.")
        self._say("")
        self._say("  1  Skip for now")
        self._say("  2  Set it up here")
        answer = self._choose(["skip", "set-up"], default=1, prompt="Proxy")
        if answer is None:
            return WIZARD_PREVIOUS
        if answer == 0:
            self._proxy = WizardProxy()
            return WIZARD_NEXT

        self._say("")
        self._say("ss://… and vless://… share links are understood.")
        nodes = []
        while True:
            answer = self._text(f"Add link {len(nodes) + 1} (empty to stop adding)", "")
            if answer is None:
                return WIZARD_PREVIOUS
            if not answer:
                break
            try:
                nodes.append(parse_share_link(answer))
            except ValueError as error:
                self._say(f"{error}")
                continue
            self._say(f"  added {nodes[-1].name or nodes[-1].id}")
        if not nodes:
            self._say("No links, so nothing to go out through.")
            self._proxy = WizardProxy()
            return WIZARD_NEXT

        proxy = WizardProxy(is_enabled=True, nodes=tuple(nodes))
        self._say("")
        if is_serving:
            self._say("Everything your devices send is routed through it, with")
            self._say("Chinese destinations going out directly.")
            answer = self._yes_no(
                "Also publish a SOCKS port that bypasses the proxy", default=False
            )
            if answer is None:
                return WIZARD_PREVIOUS
            proxy.is_socks_direct_enabled = answer
            if answer:
                port = self._port("SOCKS port for that", proxy.socks_direct_port)
                if port is None:
                    return WIZARD_PREVIOUS
                proxy.socks_direct_port = port
        else:
            answer = self._port(
                "SOCKS port applications point at", proxy.socks_proxy_port
            )
            if answer is None:
                return WIZARD_PREVIOUS
            proxy.is_socks_proxy_enabled = True
            proxy.socks_proxy_port = answer

        answer = self._yes_no("Send this box's own traffic through it", default=False)
        if answer is None:
            return WIZARD_PREVIOUS
        proxy.is_local = answer
        self._proxy = proxy
        return WIZARD_NEXT

    def _yes_no(self, question: str, *, default: bool):
        """Ask something with two answers.

        Args:
            question: What to ask, without its question mark.
            default: What Enter takes.

        Returns:
            The answer, or None to step back.
        """
        # The default spelled out beside the choices, not only carried by the
        # capital letter: every other prompt here shows its default as a
        # value, and this one reading differently is one somebody skims.
        shown = "Y/n, Y" if default else "y/N, N"
        while True:
            answer = self._prompt(f"{question}? [{shown}]")
            if answer == WIZARD_BACK:
                return None
            if not answer:
                return default
            if answer in ("y", "yes"):
                return True
            if answer in ("n", "no"):
                return False
            print("  Answer y or n, or b to step back.")

    def _port(self, question: str, default: int):
        """Ask for a TCP port.

        Args:
            question: What the port is for.
            default: What Enter takes.

        Returns:
            The port, or None to step back.
        """
        while True:
            answer = self._text(question, str(default))
            if answer is None:
                return None
            if answer.isdigit() and 1 <= int(answer) <= 65535:
                return int(answer)
            self._say("A port is a number from 1 to 65535.")

    def _review(self) -> int:
        """Everything chosen, and what saying yes to it does.

        The last screen before anything is written, and the only one that
        says so: past here the interfaces are taken over, the firewall is
        replaced and the services start.
        """
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
        if self._proxy.is_enabled:
            self._say(f"  proxy          {len(self._proxy.nodes)} exit nodes")
            if self._proxy.is_socks_proxy_enabled:
                self._say(
                    f"                 SOCKS {self._proxy.socks_proxy_port}, "
                    f"through the proxy"
                )
            if self._proxy.is_socks_direct_enabled:
                self._say(f"                 SOCKS {XRAY_SOCKS_PORT}, direct")
            if self._proxy.is_local:
                self._say("                 this box's own traffic too")
        else:
            self._say("  proxy          off")
        self._say(f"  language       {WIZARD_LANGUAGE_NAMES[self._language]}")
        self._say("")
        if ROUTER_MODES_BY_KEY[self._mode].is_addressing_owned:
            self._say("Saying yes here takes the interfaces over, replaces the")
            self._say("firewall and starts the services.")
            self._say("")
            # Said to everyone, because whether this is being read over one
            # of these ports is not something to work out: sudo hides what
            # sshd set, and a serial console, a KVM or a shell inside a shell
            # would each answer differently. The sentence is true either way,
            # and the one that matters is the second — that nothing is left
            # half done.
            self._say("The initialization process will finish on its own,")
            self._say("network might be interrupted, please reconnect when")
            self._say("interruption happens.")
            self._say("")
            self._say(
                f"The panel will be at http://{self._address}:{self._listen_port}"
            )
            self._say(f"and the run is written to {SETUP_LOG_PATH}.")
        else:
            self._say("Saying yes here replaces the firewall and starts the")
            self._say("services. Every address on this machine is left as it")
            self._say("is, including the one this terminal is reached on.")
        if self._prompt("Start, or b to step back") == WIZARD_BACK:
            return WIZARD_PREVIOUS
        return WIZARD_NEXT

    def _plan(self):
        """The configuration the answers so far describe."""
        return RouterModePlanner(
            mode=self._mode,
            port_names=tuple(self._names),
            wan_names=(self._wan,) if self._wan else (),
            lan_names=(self._lan,) if self._lan else (),
            trunk_name=self._lan if self._mode == ROUTER_LAYOUT_ONE_ARM else "",
            lan_address=self._address,
            lan_prefix_len=self._prefix_len,
            upstream_gateway=self._upstream or None,
            lan_vlan_id=self._lan_vlan_id,
        ).plan()

    def _frame(self, step: int, total: int) -> None:
        """Draw the wordmark, the step and what it asks.

        Args:
            step: The one-based screen being drawn.
            total: How many there are.
        """
        _headline(f"{WIZARD_LABEL} {step}/{total}", title=WIZARD_TITLES[step - 1])
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


def _headline(right: str, *, title: str = "") -> None:
    """The one rule every screen opens with.

    One line rather than a title above a separator: a terminal that scrolls
    between screens leaves a stack of separators, and a terminal that clears
    loses the title above the fold. The rule is the title.

    Args:
        right: What sits at the right end — a counter, or the screen's name
            when it is not one of the questions.
        title: What this screen is about, on its own line under the rule.
            Empty when ``right`` already says it.
    """
    dashes = WIZARD_WIDTH - len(WIZARD_WORDMARK) - len(right) - 2
    print()
    print()
    print(f"{WIZARD_WORDMARK} {'─' * max(1, dashes)} {right}")
    print()
    if title:
        print(f"  {title}")
        print()


def context() -> dict:
    """The same facts the screens ask against, for a browser to ask with.

    Gathered here rather than in the server, so both ways of answering are
    looking at one machine's ports, one list of modes and one list of
    modules — a browser offered a mode the terminal would not offer is a
    second wizard to keep in step.

    Returns:
        The ports, the modes they allow, the modules that could be installed,
        and what each question starts at. Every word a person reads is named
        rather than written: the page words a mode, a module and a consent
        from its own catalog.

    Raises:
        WizardAborted: When this machine has nothing to configure.
    """
    links = [link for link in RouterLinkStatus().all_links() if link.name != "lo"]
    links.sort(key=_wired_first)
    if not links:
        raise WizardAborted(
            "this machine has no network interface; a gateway needs at least one"
        )
    wired_count = sum(1 for link in links if not link.is_wifi)
    return {
        "interfaces": [
            {
                "name": link.name,
                "is_wired": not link.is_wifi,
                "ipv4_address": link.ipv4_address or "",
                "has_route": _has_route(link.name),
                "upstream_gateway": _gateway_of(link.name),
            }
            for link in links
        ],
        "modes": [
            {
                "key": mode.key,
                "port_count": mode.port_count,
                "is_wire_needed": mode.is_wire_needed,
                "is_addressing_owned": mode.is_addressing_owned,
                "has_caution": bool(mode.caution),
            }
            for mode in modes_for(len(links), wired_count)
        ],
        "password_rules": {
            "panel": PASSWORDS_PANEL_RULES.to_dict(),
            "vault": PASSWORDS_MASTER_RULES.to_dict(),
        },
        "defaults": {
            "address": ROUTER_MODE_DEFAULT_LAN_ADDRESS,
            "prefix_len": ROUTER_MODE_DEFAULT_PREFIX_LEN,
            "lan_vlan_id": ROUTER_MODE_DEFAULT_LAN_VLAN,
            "socks_proxy_port": XRAY_SOCKS_PORT,
            "socks_direct_port": XRAY_SOCKS_PORT,
            "listen_port": WEB_DEFAULT_LISTEN_PORT,
        },
    }


def welcome() -> None:
    """What this is, before the questions start.

    Shown on the way into the terminal's own screens. A machine that can open
    a browser gets :func:`offer_browser` instead, which says the same thing
    and then waits.

    Raises:
        SystemExit: When the person interrupts or standard input ends.
    """
    _headline(WIZARD_WELCOME_TITLE)
    _intro()
    print()
    try:
        input("  Press Enter to begin: ")
    except (EOFError, KeyboardInterrupt):
        print(f"\n\n  {WIZARD_ABORTED}\n", file=sys.stderr)
        raise SystemExit(WIZARD_STOPPED_STATUS) from None


def offer_browser(*, urls: list, token: str, arrived, is_opened: bool = True) -> bool:
    """Say where the wizard can be answered, and wait for it to be.

    Offered whatever this machine is. A box set up over SSH has no browser of
    its own and every reason to be answered from one — the person is sitting
    at a machine that has one — so the addresses are the point rather than the
    fallback, and this says so.

    Args:
        urls: Every address this machine can be reached at, in the order they
            should be tried.
        token: The one-time token the link carries.
        arrived: Called to ask whether the browser has answered yet. It waits
            out its own interval, so this loop does not spin.
        is_opened: Whether a browser was opened here. False on a machine with
            nothing to open one, where the addresses are the only way in.

    Returns:
        True when the browser answered, False when whoever is at the keyboard
        would rather answer here.

    Raises:
        SystemExit: When the person interrupts or standard input ends.
    """
    _headline(WIZARD_WELCOME_TITLE)
    _intro()
    print()
    if is_opened:
        print("  Opening it in a browser. It is the same wizard, and this terminal")
        print("  follows along. From another machine, open:")
    else:
        print("  Answer it in a browser — it is the same wizard, and this terminal")
        print("  follows along. From any machine that can reach this one, open:")
    print()
    for url in urls:
        print(f"    {url}?token={token}")
    print()
    print("  The link is good for this run only.")
    print()
    print("  Or answer here instead.")
    print()
    # No newline, and flushed: this is a prompt somebody is looking at, and
    # stdout is only line-buffered when it is a terminal. Nothing else is
    # printed until the browser answers or Enter is pressed.
    print("  Continue in terminal (will close server): ", end="")
    sys.stdout.flush()
    is_watching = True
    try:
        while True:
            if arrived():
                return True
            if not is_watching:
                continue
            wanted = _is_terminal_wanted()
            if wanted is None:
                # Nobody is at the keyboard — this was started from a script,
                # or its input has been closed. Watching a stream that is at
                # end of file only spins.
                is_watching = False
            elif wanted:
                return False
    except (EOFError, KeyboardInterrupt):
        print(f"\n\n  {WIZARD_ABORTED}\n", file=sys.stderr)
        raise SystemExit(WIZARD_STOPPED_STATUS) from None


def _intro() -> None:
    """What this takes and how to work it, said the same way on both ways in.

    One line about the box and one about the controls: whoever is reading
    this wants to know how long it takes and how to get out of it, and
    everything else is on the screens that follow.
    """
    print("  Pour a coffee and sit back — this takes about a minute.")
    print()
    print("  Nothing is written until the last screen confirms it. Ctrl-C stops")
    print("  at any point, and b at a prompt steps back a question.")


def _is_terminal_wanted():
    """Whether somebody asked to answer in the terminal after all.

    Returns:
        True when a line is waiting on standard input, which is the Continue
        prompt being answered, and None when there is nothing left to read
        from, which is what a closed input looks like.
    """
    try:
        ready, _, _ = select.select([sys.stdin], [], [], 0)
    except (OSError, ValueError):
        return None
    if not ready:
        return False
    line = sys.stdin.readline()
    if line == "":
        return None
    return True


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


def finish(*, panel_url: str, link: str = "", note: str = "", joined=None) -> None:
    """The last screen: where the panel is, and how a device joins it.

    Drawn after the machine has been changed rather than before, because the
    enrollment link is generated by the panel and only exists once it is running.
    It waits, so somebody can paste the link into a device while the link is
    still on the screen, and then says what arrived.

    Args:
        panel_url: Where the panel answers.
        link: An enrollment link to paste into a device, empty when none
            could be generated.
        note: Why there is no link, when there is none.
        joined: Called after the wait for the names of the devices that came
            in, so this module reads no configuration of its own.
    """
    _headline(WIZARD_DONE_TITLE)
    print(f"  The panel is at   {panel_url}")
    print()
    if link:
        print("  To bring a device in, install the agent on it and run:")
        print()
        print(f"    nagent connect '{link}'")
        print()
        print("  The link lasts thirty minutes. The panel's Devices page generates")
        print("  more, one per device.")
    else:
        print(
            f"  {note}" if note else "  The Devices page generates an enrollment link."
        )
    print()
    _watch(joined)
    print()


def _watch(joined) -> None:
    """Name each device as it arrives, until somebody says they are done.

    Shown one at a time rather than counted at the end, because the point of
    waiting here is to watch a device you just pasted the link into come in —
    a total afterwards tells you it worked without telling you when.

    Args:
        joined: Called for the names of the devices that have enrolled.
    """
    print("  Press Enter when you have finished.")
    print()
    seen: set = set()
    while True:
        for name in list(joined() if joined else []):
            if name not in seen:
                seen.add(name)
                print(f"    joined  {name}")
        if _is_enter_pressed():
            break
    if not seen:
        print("    nothing joined; the Devices page generates another link.")


def _is_enter_pressed() -> bool:
    """Whether a line arrived while waiting out one poll interval.

    Returns:
        True when there is a line to read or standard input has ended, which
        is what a pipe looks like and what stops this hanging out of a
        terminal.
    """
    try:
        ready, _, _ = select.select([sys.stdin], [], [], WIZARD_POLL_INTERVAL_S)
    except (OSError, ValueError):
        return True
    if not ready:
        return False
    return sys.stdin.readline() == "" or True

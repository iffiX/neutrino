"""Driving one radio's `wpa_supplicant`: scanning, joining, and what it did.

Association is layer 2, and `ip` cannot do it. `wpa_supplicant` is what every
manager on every distribution drives for this — NetworkManager included, over
D-Bus — so driving it directly is one layer fewer rather than a layer more.

The supplicant decides which network to associate with, out of the ones in its
configuration that are actually in range. So joining a network is not a command
here: it is writing the network into `config/`, rendering, and telling the
supplicant to read the file again.

Not pure: talks to a running supplicant and to systemd.
"""

import subprocess
import time

from neutrino_hub.modules.router.constants import (
    ROUTER_SUPPLICANT_CONTROL_DIR,
    ROUTER_SUPPLICANT_UNIT,
    router_supplicant_config_path,
)
from neutrino_hub.utils.json_file import write_generated
from neutrino_hub.utils.subprocess_run import run

# --- config ---
SUPPLICANT_CLI = "wpa_cli"
# A scan takes a few seconds of radio time, and a radio that is associating
# will not answer until it has finished.
SUPPLICANT_SCAN_TIMEOUT_S = 45
# How long an association is given before it is called a failure. A wrong
# passphrase is discovered in a second or two; a distant access point on a busy
# channel can take most of this.
SUPPLICANT_JOIN_TIMEOUT_S = 40
SUPPLICANT_POLL_INTERVAL_S = 1.0

# What `wpa_cli status` calls a finished association, and the states it passes
# through on the way to failing.
SUPPLICANT_STATE_COMPLETED = "COMPLETED"
SUPPLICANT_STATE_DISCONNECTED = "DISCONNECTED"

# What the flags column of a scan result holds for each way of authenticating.
# Read in this order: a network offering both WPA3 and WPA2 is joined as WPA2,
# which associates with either.
SUPPLICANT_FLAG_PSK = "-PSK"
SUPPLICANT_FLAG_SAE = "SAE"
SUPPLICANT_FLAG_ENTERPRISE = "-EAP"


def write_config(interface: str, connections) -> bool:
    """Render a radio's configuration and write it, if it would differ.

    Args:
        interface: The radio.
        connections: The networks the box knows, a
            :class:`RouterConnectionSet`.

    Returns:
        True when the file changed, which is the caller's signal that the
        supplicant has to be told to read it again.
    """
    from neutrino_hub.modules.router.supplicant_renderer import (
        RouterSupplicantRenderer,
    )
    from neutrino_hub.modules.router.wifi import regulatory_domain

    text = RouterSupplicantRenderer(
        connections=connections, country_code=regulatory_domain()
    ).render()
    path = router_supplicant_config_path(interface)
    if path.is_file() and path.read_text(encoding="utf-8") == text:
        return False
    # 0600: it holds every passphrase the box knows.
    write_generated(path, text, mode=0o600)
    return True


class RouterWifiClient:
    """Scans and reports on one wireless interface."""

    def __init__(self, *, interface: str):
        """
        Args:
            interface: Wireless interface name, for example ``wlp3s0``.
        """
        self._interface = interface

    @property
    def unit(self) -> str:
        """The systemd unit running this radio's supplicant."""
        return ROUTER_SUPPLICANT_UNIT.format(interface=self._interface)

    @property
    def is_running(self) -> bool:
        """Whether the supplicant is up on this radio."""
        return run(
            ["systemctl", "is-active", "--quiet", self.unit], is_checked=False
        ).is_success

    def start(self) -> None:
        """Ask for the supplicant on this radio, and keep it started.

        Asked for, not waited on: this unit is ordered `After=` the router
        unit and the applier runs inside it, so waiting would be waiting on
        something systemd will not start yet.
        """
        run(["systemctl", "enable", self.unit], is_checked=False)
        run(["systemctl", "start", "--no-block", self.unit], is_checked=False)

    def stop(self) -> None:
        """Stop the supplicant and leave the radio idle."""
        run(["systemctl", "disable", "--now", self.unit], is_checked=False)

    def reconfigure(self) -> None:
        """Tell the supplicant to read its configuration file again.

        This is what makes a newly written network live. The supplicant
        re-reads, sees the network, and associates with it if it is in range
        and nothing it prefers is.

        Raises:
            subprocess.CalledProcessError: When the supplicant cannot be
                reached, which means it is not running on this radio.
        """
        self._cli("reconfigure")

    def scan(self) -> list:
        """Ask the radio what it can see.

        Returns:
            One entry per network name, strongest first — a mesh publishing
            one name from three radios is one choice to the person picking,
            not three.

        Raises:
            subprocess.CalledProcessError: When the radio will not scan,
                which normally means the supplicant is not running on it.
        """
        self._cli("scan", timeout_s=SUPPLICANT_SCAN_TIMEOUT_S)
        # The scan runs in the background and the results come from a second
        # call. Asking immediately returns the previous scan, which on a radio
        # that has just started is nothing at all.
        time.sleep(SUPPLICANT_POLL_INTERVAL_S)
        result = self._cli("scan_results", timeout_s=SUPPLICANT_SCAN_TIMEOUT_S)
        strongest: dict[str, dict] = {}
        for line in result.splitlines()[1:]:
            found = _parse_scan_line(line)
            if found is None:
                continue
            previous = strongest.get(found["ssid"])
            if previous is None or found["signal_percent"] > previous["signal_percent"]:
                strongest[found["ssid"]] = found
        return sorted(
            strongest.values(), key=lambda item: item["signal_percent"], reverse=True
        )

    def joined_ssid(self) -> str | None:
        """The network this radio is associated with.

        Returns:
            Its name, or None when the radio is idle.
        """
        status = self.status()
        if status.get("wpa_state") != SUPPLICANT_STATE_COMPLETED:
            return None
        return status.get("ssid") or None

    def status(self) -> dict:
        """What the supplicant says it is doing.

        Returns:
            Its `key=value` report as a dictionary, empty when it cannot be
            reached — which reads the same as a radio doing nothing.
        """
        try:
            text = self._cli("status")
        except (subprocess.SubprocessError, OSError):
            return {}
        report = {}
        for line in text.splitlines():
            key, separator, value = line.partition("=")
            if separator:
                report[key.strip()] = value.strip()
        return report

    def wait_for_association(
        self, *, timeout_s: int = SUPPLICANT_JOIN_TIMEOUT_S
    ) -> str:
        """Wait until the radio has joined something, or give up.

        Args:
            timeout_s: How long to wait.

        Returns:
            The network it joined.

        Raises:
            TimeoutError: When it does not join in time. The message says what
                the supplicant was doing when the wait ended, because "wrong
                passphrase" and "out of range" look different there.
        """
        deadline = time.monotonic() + timeout_s
        last_state = ""
        while time.monotonic() < deadline:
            status = self.status()
            last_state = status.get("wpa_state", "")
            if last_state == SUPPLICANT_STATE_COMPLETED:
                return status.get("ssid", "")
            time.sleep(SUPPLICANT_POLL_INTERVAL_S)
        raise TimeoutError(_readable_failure(last_state))

    def _cli(self, *arguments: str, timeout_s: int = 15) -> str:
        """Run one `wpa_cli` command against this radio.

        Args:
            arguments: The command and its arguments.
            timeout_s: Seconds before it is killed.

        Returns:
            What it printed.

        Raises:
            subprocess.CalledProcessError: When the command fails or the
                supplicant answers ``FAIL``.
        """
        result = run(
            [
                SUPPLICANT_CLI,
                "-p",
                str(ROUTER_SUPPLICANT_CONTROL_DIR),
                "-i",
                self._interface,
                *arguments,
            ],
            timeout_s=timeout_s,
            is_checked=False,
        )
        text = result.stdout.strip()
        if not result.is_success or text == "FAIL":
            raise subprocess.CalledProcessError(
                result.exit_code or 1,
                result.command,
                output=result.stdout,
                stderr=(result.stderr or text).strip() or "no answer",
            )
        return text


def _parse_scan_line(line: str) -> dict | None:
    """One row of `wpa_cli scan_results`.

    Args:
        line: The row, tab separated: bssid, frequency, signal, flags, ssid.

    Returns:
        What the panel draws, or None for a row with no network name — a
        hidden network answers a scan with an empty one, and there is nothing
        to offer somebody picking from a list.
    """
    parts = line.split("\t")
    if len(parts) < 5:
        return None
    _, _, signal, flags, ssid = parts[0], parts[1], parts[2], parts[3], parts[4]
    if not ssid:
        return None
    return {
        "ssid": ssid,
        "signal_percent": _signal_percent(signal),
        "security": _security(flags),
        "is_enterprise": SUPPLICANT_FLAG_ENTERPRISE in flags,
    }


def _security(flags: str) -> str:
    """How a network in a scan asks to be authenticated to.

    Args:
        flags: The flags column, for example ``[WPA2-PSK-CCMP][ESS]``.

    Returns:
        ``WPA-PSK``, ``SAE``, ``802.1X`` or an empty string for an open
        network. A network offering both WPA3 and WPA2 reads as WPA2, which
        associates with either.
    """
    if SUPPLICANT_FLAG_ENTERPRISE in flags:
        return "802.1X"
    if SUPPLICANT_FLAG_PSK in flags:
        return "WPA-PSK"
    if SUPPLICANT_FLAG_SAE in flags:
        return "SAE"
    return ""


def _signal_percent(level: str) -> int:
    """Turn a scan's signal level into the percentage the panel draws.

    Args:
        level: The level in dBm, as the supplicant reports it.

    Returns:
        0 to 100, on the same mapping the link reader uses so one network does
        not read differently in the scan and on the interface.
    """
    try:
        dbm = int(float(level))
    except ValueError:
        return 0
    return max(0, min(100, 2 * (dbm + 100)))


def _readable_failure(state: str) -> str:
    """What to say when an association did not finish.

    Args:
        state: The last `wpa_state` seen.

    Returns:
        A sentence naming the likely cause.
    """
    if state in ("", SUPPLICANT_STATE_DISCONNECTED):
        return "that network did not answer; it may be out of range"
    if state.startswith("4WAY") or state == "ASSOCIATING":
        return "the network refused the passphrase"
    return f"the radio did not finish joining; it is {state or 'not saying'}"

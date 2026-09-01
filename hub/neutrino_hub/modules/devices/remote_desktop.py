"""Reading remote-desktop software on a device over SSH.

Two products are covered, AnyDesk and ToDesk, because the hub lives in one
country and its owner is often in another — remote desktop is the way back to
a work machine. What this reads is the part only the running product knows:
whether its service is up, the session id someone connects to, and — for
AnyDesk — the unattended password. Putting either product on a machine, or
taking it off, is a module the agent reconciles from ``manifests/``; a second
installer here would be a second answer to the same question.

Commands run with a forced UTF-8 locale: AnyDesk refuses to start without one,
and an SSH session carries none by default.
"""

import shlex
from collections.abc import AsyncIterator
from dataclasses import dataclass

from neutrino_hub.modules.devices.constants import SSH_UNREACHABLE_STATUS
from neutrino_hub.modules.devices.ssh_ops import DeviceSshOperator

SUPPORTED_PRODUCTS = ("anydesk", "todesk")

# How each product identifies itself on a device. ToDesk here is the Host
# build — the unattended one a gateway needs — whose package, service, and
# install path all differ from the regular ToDesk desktop app.
_PRODUCT_UNITS = {
    "anydesk": {
        "binary": "anydesk",
        "service": "anydesk",
        "package": "anydesk",
        "paths": ("/usr/bin/anydesk",),
    },
    "todesk": {
        "binary": "todesk",
        "service": "todeskd",
        "package": "todesk",
        "paths": ("/opt/todesk/bin/ToDesk",),
    },
}


@dataclass
class RemoteDesktopStatus:
    """What a device's remote-desktop software is doing.

    Attributes:
        product: Either ``anydesk`` or ``todesk``.
        is_installed: Whether the product is on the device.
        is_running: Whether its background service is active.
        session_id: The id to connect to, when it can be read.
        can_set_password: Whether an unattended password can be set headless.
        unreachable: Why the device could not be asked, empty when it was.
            A machine that is off, a wrong password and a changed host key all
            come back as one failed command, and reporting that as "not
            installed" advises installing software onto a device nobody can
            reach — and contradicts what the module list says about the same
            machine.
    """

    product: str
    is_installed: bool
    is_running: bool
    session_id: str | None
    can_set_password: bool
    unreachable: str = ""


class RemoteDesktopManager:
    """Reads and changes remote-desktop software on one device."""

    def __init__(self, *, operator: DeviceSshOperator):
        """
        Args:
            operator: An SSH operator bound to the target device.
        """
        self._operator = operator

    async def status(self, product: str) -> RemoteDesktopStatus:
        """Report a product's state on the device.

        A stopped service is started here rather than merely reported: a device
        with the product installed but its daemon down cannot be connected to,
        and the caller has root, so the useful thing is to bring it up. Nothing
        raises on a probe failure — an unreachable device reads as "not
        installed" rather than erroring the whole page.

        Args:
            product: Either ``anydesk`` or ``todesk``.

        Returns:
            The product's status: whether it is there, whether it is running,
            and the address someone can connect to.

        Raises:
            ValueError: If the product is unknown.
        """
        self._require_product(product)
        units = _PRODUCT_UNITS[product]
        service = units["service"]

        # ToDesk installs outside PATH, so `command -v` alone misses it and the
        # panel wrongly reads "not installed". Its install path and package
        # database entry are both checked as well.
        checks = [f"command -v {units['binary']}"]
        checks += [f"ls {path} 2>/dev/null" for path in units["paths"]]
        checks += [
            f"dpkg -s {units['package']} 2>/dev/null",
            f"rpm -q {units['package']} 2>/dev/null",
        ]
        code, output = await self._operator.run_once(" || ".join(checks))
        if code == SSH_UNREACHABLE_STATUS:
            return RemoteDesktopStatus(
                product=product,
                is_installed=False,
                is_running=False,
                session_id=None,
                can_set_password=product == "anydesk",
                unreachable=output.strip() or "the device could not be reached",
            )
        if code != 0:
            return RemoteDesktopStatus(
                product=product,
                is_installed=False,
                is_running=False,
                session_id=None,
                can_set_password=product == "anydesk",
            )

        _, running = await self._operator.run_once(f"systemctl is-active {service}")
        if running.strip() != "active":
            await self._operator.run_privileged_once(
                f"systemctl enable --now {service}"
            )
            _, running = await self._operator.run_once(f"systemctl is-active {service}")

        return RemoteDesktopStatus(
            product=product,
            is_installed=True,
            is_running=running.strip() == "active",
            session_id=await self._session_id(product),
            can_set_password=product == "anydesk",
        )

    async def set_password_stream(
        self, product: str, *, password: str
    ) -> AsyncIterator[str]:
        """Set the unattended-access password headless, and enable unattended
        access so a connection needs no one to click Accept on the device.

        Args:
            product: Either ``anydesk`` or ``todesk``.
            password: The unattended password to set.

        Yields:
            Progress lines and the command's output.

        Raises:
            ValueError: If the product is unknown.
        """
        self._require_product(product)
        if product != "anydesk":
            yield (
                "[ToDesk has no headless password command; set it once in the "
                "ToDesk app on the device, then its id shows here]\n"
            )
            return
        # Set it as the login user, not through sudo. AnyDesk keeps two separate
        # configs — the system service under /etc/anydesk, and the desktop
        # session under the user's ~/.anydesk. A person connecting back to their
        # machine reaches the desktop session, so a password set as root lands
        # in the wrong place and appears not to change anything, which is exactly
        # what went wrong before. --set-password also turns on unattended
        # access, so the connection needs no one to click Accept on the device.
        yield "[setting the AnyDesk unattended password for this user]\n"
        command = (
            "LANG=C.UTF-8 LC_ALL=C.UTF-8 sh -c "
            f"{self._quote(f'echo {self._quote(password)} | anydesk --set-password && anydesk --get-id')}"
        )
        async for chunk in self._operator.run_stream(command):
            yield chunk
        yield "\n[done — connect with the AnyDesk id above and this password]\n"

    async def _session_id(self, product: str) -> str | None:
        if product == "anydesk":
            code, output = await self._operator.run_once("anydesk --get-id")
            if code == 0 and output.strip().isdigit():
                return output.strip()
            return None
        # ToDesk has no id-query command — its binaries are daemons, and running
        # one directly starts a second server rather than answering. The id its
        # servers assign lands in config_slave.ini once someone signs in on the
        # device, so that one file is read. config.ini is deliberately excluded:
        # it holds unrelated long numbers (a download timestamp among them) that
        # a looser search mistakes for an id.
        code, output = await self._operator.run_privileged_once(
            "grep -oE '[0-9]{6,12}' /opt/todesk/config/config_slave.ini "
            "2>/dev/null | head -1"
        )
        if code == 0 and output.strip().isdigit():
            return output.strip()
        return None

    def _require_product(self, product: str) -> None:
        if product not in SUPPORTED_PRODUCTS:
            raise ValueError(
                f"unknown remote desktop product {product!r}; "
                f"expected one of {', '.join(SUPPORTED_PRODUCTS)}"
            )

    def _quote(self, value: str) -> str:
        return shlex.quote(value)

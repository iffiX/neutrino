"""Reading remote-desktop software on a device over SSH.

AnyDesk is the one product covered. What this reads is the part only the
running product knows: whether its service is up, the session id someone
connects to, and the unattended password. AnyDesk is a user-tier module —
the person puts it on the machine, and the hub only detects and manages
what is already there.

Commands run with a forced UTF-8 locale: AnyDesk refuses to start without one,
and an SSH session carries none by default.
"""

import shlex
from collections.abc import AsyncIterator
from dataclasses import dataclass

from neutrino_hub.modules.devices.constants import SSH_UNREACHABLE_STATUS
from neutrino_hub.modules.devices.ssh_ops import DeviceSshOperator

SUPPORTED_PRODUCTS = ("anydesk",)

# How the product identifies itself on a device.
_PRODUCT_UNITS = {
    "anydesk": {
        "binary": "anydesk",
        "service": "anydesk",
        "package": "anydesk",
        "paths": ("/usr/bin/anydesk",),
    },
}


@dataclass
class RemoteDesktopStatus:
    """What a device's remote-desktop software is doing.

    Attributes:
        product: One of :data:`SUPPORTED_PRODUCTS`.
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
            product: One of :data:`SUPPORTED_PRODUCTS`.

        Returns:
            The product's status: whether it is there, whether it is running,
            and the address someone can connect to.

        Raises:
            ValueError: If the product is unknown.
        """
        self._require_product(product)
        units = _PRODUCT_UNITS[product]
        service = units["service"]

        # The binary, its install path and the package database are all
        # checked, so a build outside PATH still reads installed.
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
                can_set_password=True,
                unreachable=output.strip() or "the device could not be reached",
            )
        if code != 0:
            return RemoteDesktopStatus(
                product=product,
                is_installed=False,
                is_running=False,
                session_id=None,
                can_set_password=True,
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
            session_id=await self._session_id(),
            can_set_password=True,
        )

    async def set_password_stream(
        self, product: str, *, password: str
    ) -> AsyncIterator[str]:
        """Set the unattended-access password headless, and enable unattended
        access so a connection needs no one to click Accept on the device.

        Args:
            product: One of :data:`SUPPORTED_PRODUCTS`.
            password: The unattended password to set.

        Yields:
            Progress lines and the command's output.

        Raises:
            ValueError: If the product is unknown.
        """
        self._require_product(product)
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

    async def _session_id(self) -> str | None:
        code, output = await self._operator.run_once("anydesk --get-id")
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

"""Which seat answers for this machine's screen.

A seat says who is signed in at the screen, whether there is a desktop to
share, how many peers are connected to the direct port, and what a peer
would wait on at a seated screen, and asks the seated person for what
RustDesk needs granted there. Each platform has its own.
"""

from neutrino_agent.rdp.darwin_seat import DarwinSeat
from neutrino_agent.rdp.linux_seat import LinuxSeat
from neutrino_agent.rdp.windows_seat import WindowsSeat


def seat_for(os_name: str):
    """The seat of one operating system.

    Args:
        os_name: The platform's ``os_name``: ``linux``, ``windows`` or
            ``darwin``.

    Returns:
        That platform's seat; any other name gets the Linux one.
    """
    if os_name == "windows":
        return WindowsSeat()
    if os_name == "darwin":
        return DarwinSeat()
    return LinuxSeat()

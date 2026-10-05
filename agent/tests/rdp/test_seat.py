"""seat_for: each operating system is read by its own seat."""

import pytest

from neutrino_agent.rdp.darwin_seat import DarwinSeat
from neutrino_agent.rdp.host import RdpShareHost
from neutrino_agent.rdp.linux_seat import LinuxSeat
from neutrino_agent.rdp.seat import seat_for
from neutrino_agent.rdp.windows_seat import WindowsSeat
from neutrino_agent.platforms.darwin import DarwinPlatform
from neutrino_agent.platforms.linux import LinuxPlatform
from neutrino_agent.platforms.windows import WindowsPlatform


@pytest.mark.parametrize(
    "os_name, seat_class",
    [
        ("linux", LinuxSeat),
        ("windows", WindowsSeat),
        ("darwin", DarwinSeat),
        ("", LinuxSeat),
    ],
)
def test_each_os_is_read_by_its_own_seat(os_name, seat_class):
    assert type(seat_for(os_name)) is seat_class


@pytest.mark.parametrize(
    "platform_class, seat_class",
    [
        (LinuxPlatform, LinuxSeat),
        (WindowsPlatform, WindowsSeat),
        (DarwinPlatform, DarwinSeat),
    ],
)
def test_a_host_given_no_seat_reads_its_platforms(tmp_path, platform_class, seat_class):
    host = RdpShareHost(
        platform=platform_class(),
        store=None,
        credentials_dir=str(tmp_path),
        state_dir=str(tmp_path),
        log=print,
    )

    assert type(host._seat) is seat_class
    assert (
        type(host._applier).__name__
        == {
            LinuxSeat: "RemoteDesktopLinuxApplier",
            WindowsSeat: "RemoteDesktopWindowsApplier",
            DarwinSeat: "RemoteDesktopDarwinApplier",
        }[seat_class]
    )

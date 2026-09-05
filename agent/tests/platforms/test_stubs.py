"""The darwin and windows stubs: what a machine cannot do is said, not faked."""

import pytest

from neutrino_agent.platforms.base import PlatformUnsupportedError
from neutrino_agent.platforms.windows import WindowsPlatform


def test_windows_has_no_peer_identity_yet():
    with pytest.raises(PlatformUnsupportedError):
        WindowsPlatform().read_peer_identity(object())
    with pytest.raises(PlatformUnsupportedError):
        WindowsPlatform().control_socket_path()

"""The transport's directories as its applier makes them.

What this pins: the key directory is the transport's own, mode 0700, and
the configuration root above it lets the account pass, mode 0711, since the
account reaches its key through it.
"""

import stat

from neutrino_hub.modules.transport import ops


def test_the_key_directory_is_private_under_a_root_the_account_passes(
    tmp_path, monkeypatch
):
    root = tmp_path / "hub"
    root.mkdir(mode=0o700)
    monkeypatch.setattr(ops, "TRANSPORT_KEY_DIR", root / "transport")
    monkeypatch.setattr(ops, "is_linux", lambda: True)
    monkeypatch.setattr(ops, "has_account", lambda: False)

    assert ops.ensure_key_dir() is True
    assert ops.ensure_key_dir() is False

    assert stat.S_IMODE((root / "transport").stat().st_mode) == 0o700
    assert stat.S_IMODE(root.stat().st_mode) == 0o711

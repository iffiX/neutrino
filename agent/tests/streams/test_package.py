"""The package stream: bytes down as they land, a digest at the close.

What these pin: a package of many records lands whole, the file is handed over only
once the hub's close named a ``sha256`` that matches, a mismatch is
refused and leaves no file, a refusal from the hub passes its code
through and leaves no file, and a socket that dropped mid-transfer leaves
no file and is ``hub_unreachable``. The one file a transfer leaves on
purpose, the agent's own package, is removed by the start-up sweep.
"""

import hashlib
import os

from neutrino_agent.streams.package import PackageStream, remove_stale
from tests.streams.fake_channel import FakeChannel


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def leftovers(directory) -> list:
    return sorted(os.listdir(directory)) if os.path.isdir(directory) else []


def received(tmp_path, chunks, close=None) -> tuple:
    """Feed the chunks and the close, then receive; returns (outcome, channel)."""
    channel = FakeChannel(stream_id="3")
    for chunk in chunks:
        channel.feed(("data", chunk))
    if close is not None:
        channel.feed(("close", close[0], close[1]))
    return (
        PackageStream(channel, directory=str(tmp_path / "packages")).receive(),
        channel,
    )


def test_the_bytes_land_in_a_file_the_close_vouches_for(tmp_path):
    outcome, channel = received(
        tmp_path,
        [b"!<arch>", b"deb bytes"],
        ("", {"sha256": sha256(b"!<arch>deb bytes")}),
    )

    assert set(outcome) == {"path", "sha256"}
    assert outcome["sha256"] == sha256(b"!<arch>deb bytes")
    assert outcome["path"].startswith(str(tmp_path / "packages"))
    with open(outcome["path"], "rb") as stream:
        assert stream.read() == b"!<arch>deb bytes"
    assert channel.closed is None


def test_a_package_of_many_records_lands_whole(tmp_path):
    record = 64 * 1024
    size = 2 * 1024 * 1024 + 7
    chunks = [
        bytes([index % 251]) * min(record, size - offset)
        for index, offset in enumerate(range(0, size, record))
    ]
    data = b"".join(chunks)

    outcome, _ = received(tmp_path, chunks, ("", {"sha256": sha256(data)}))

    assert "path" in outcome
    assert os.path.getsize(outcome["path"]) == size


def test_bytes_that_do_not_match_the_digest_are_refused_and_leave_no_file(tmp_path):
    outcome, _ = received(tmp_path, [b"something else"], ("", {"sha256": "0" * 64}))

    assert outcome == {"code": "package_digest_mismatch", "params": {}}
    assert leftovers(tmp_path / "packages") == []


def test_a_close_that_names_no_digest_is_a_dropped_socket(tmp_path):
    outcome, _ = received(tmp_path, [b"half"], ("", {}))

    assert outcome == {"code": "hub_unreachable", "params": {}}
    assert leftovers(tmp_path / "packages") == []


def test_a_refusal_from_the_hub_passes_its_code_through(tmp_path):
    outcome, _ = received(
        tmp_path, [], ("module_artifact_unknown", {"artifact_key": "k"})
    )

    assert outcome == {
        "code": "module_artifact_unknown",
        "params": {"artifact_key": "k"},
    }
    assert leftovers(tmp_path / "packages") == []


def test_a_connection_that_ends_mid_transfer_leaves_no_file(tmp_path):
    outcome, _ = received(tmp_path, [b"half of it"], ("", {}))

    assert outcome == {"code": "hub_unreachable", "params": {}}
    assert leftovers(tmp_path / "packages") == []


def test_a_named_package_is_renamed_from_its_temporary_name(tmp_path):
    channel = FakeChannel(stream_id="3")
    channel.feed(("data", b"xar!"))
    channel.feed(("close", "", {"sha256": sha256(b"xar!")}))

    outcome = PackageStream(
        channel, directory=str(tmp_path / "packages"), name="neutrino_agent.pkg"
    ).receive()

    assert outcome["path"] == str(tmp_path / "packages" / "neutrino_agent.pkg")
    assert outcome["sha256"] == sha256(b"xar!")
    assert leftovers(tmp_path / "packages") == ["neutrino_agent.pkg"]


def test_a_named_package_that_does_not_match_leaves_no_file(tmp_path):
    channel = FakeChannel(stream_id="3")
    channel.feed(("data", b"xar!"))
    channel.feed(("close", "", {"sha256": "0" * 64}))

    outcome = PackageStream(
        channel, directory=str(tmp_path / "packages"), name="neutrino_agent.pkg"
    ).receive()

    assert outcome == {"code": "package_digest_mismatch", "params": {}}
    assert leftovers(tmp_path / "packages") == []


def test_a_module_package_keeps_its_temporary_name_whatever_the_close_names(
    tmp_path,
):
    outcome, _ = received(
        tmp_path, [b"x"], ("", {"sha256": sha256(b"x"), "name": "code.tar.gz"})
    )

    assert os.path.basename(outcome["path"]).startswith(".package.")


def test_the_landing_directory_is_made_root_only(tmp_path):
    outcome, _ = received(tmp_path, [b"x"], ("", {"sha256": sha256(b"x")}))

    assert "path" in outcome
    assert (os.stat(tmp_path / "packages").st_mode & 0o777) == 0o700


# --- what the next start sweeps ---


def test_the_sweep_removes_what_a_transfer_left(tmp_path):
    directory = tmp_path / "packages"
    directory.mkdir()
    (directory / ".package.abc.part").write_bytes(b"installed me")
    (directory / ".package.def.part").write_bytes(b"half")

    remove_stale(str(directory))

    assert leftovers(directory) == []
    assert directory.is_dir()


def test_the_sweep_of_a_directory_not_there_is_nothing(tmp_path):
    remove_stale(str(tmp_path / "packages"))

    assert not (tmp_path / "packages").exists()

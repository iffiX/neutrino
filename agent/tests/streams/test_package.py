"""The package stream: bytes down, credit as they land, a digest at the close.

What these pin: credit is granted as each piece is written so a package
larger than one window proceeds past it, the file is handed over only
once the hub's close named a ``sha256`` that matches, a mismatch is
refused and leaves no file, a refusal from the hub passes its code
through and leaves no file, and a socket that dropped mid-transfer leaves
no file and is ``hub_unreachable``. The one file a transfer leaves on
purpose, the agent's own package, is removed by the start-up sweep.
"""

import hashlib
import os

from neutrino_agent.constants import AGENT_WS_CHUNK_BYTES, AGENT_WS_STREAM_CREDIT_BYTES
from neutrino_agent.exceptions import GatewayUnreachable
from neutrino_agent.streams.package import PackageStream, remove_stale
from tests.streams.fake_channel import FakeChannel


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def leftovers(directory) -> list:
    return sorted(os.listdir(directory)) if os.path.isdir(directory) else []


def received(tmp_path, chunks, close=None) -> tuple:
    """Feed the chunks and the close, then receive; returns (outcome, channel)."""
    channel = FakeChannel(stream_id=3)
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

    assert set(outcome) == {"path"}
    assert outcome["path"].startswith(str(tmp_path / "packages"))
    with open(outcome["path"], "rb") as stream:
        assert stream.read() == b"!<arch>deb bytes"
    assert channel.credits[0] == AGENT_WS_STREAM_CREDIT_BYTES
    assert channel.credits[1:] == [len(b"!<arch>"), len(b"deb bytes")]
    assert channel.closed is None


def test_a_package_larger_than_one_window_is_credited_as_it_lands(tmp_path):
    size = 2 * AGENT_WS_STREAM_CREDIT_BYTES + 7
    chunks = [
        bytes([index % 251]) * min(AGENT_WS_CHUNK_BYTES, size - offset)
        for index, offset in enumerate(range(0, size, AGENT_WS_CHUNK_BYTES))
    ]
    data = b"".join(chunks)

    outcome, channel = received(tmp_path, chunks, ("", {"sha256": sha256(data)}))

    assert "path" in outcome
    assert os.path.getsize(outcome["path"]) == size
    assert channel.credits[1:] == [len(chunk) for chunk in chunks]
    assert sum(channel.credits) >= size


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


def test_a_socket_gone_before_the_first_credit_leaves_no_file(tmp_path):
    class GoneChannel(FakeChannel):
        def offer_credit(self, size):
            raise GatewayUnreachable("gone")

    outcome = PackageStream(
        GoneChannel(stream_id=3), directory=str(tmp_path / "packages")
    ).receive()

    assert outcome == {"code": "hub_unreachable", "params": {}}
    assert leftovers(tmp_path / "packages") == []


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

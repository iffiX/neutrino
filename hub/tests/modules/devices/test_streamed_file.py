"""A download written to disk as it arrives.

What these pin: a large body goes to a temporary file in 64 KB pieces,
hashed on the way, its first bytes kept; reading stops one byte past the
limit; a read that breaks off is a ConnectionError and leaves no file; a
placed download is one rename and a discarded one is gone; and a file's
digest is read in chunks.
"""

import hashlib
import os

import pytest

from neutrino_hub.modules.devices.streamed_file import file_sha256, stream_to_file

MEGABYTE = 1024 * 1024


class PiecedResponse:
    """A body handed out in the sizes asked for, breaking off where told."""

    def __init__(self, body: bytes, *, broken_at=None):
        self._body = body
        self._offset = 0
        self._broken_at = broken_at
        self.headers = {"Content-Length": str(len(body))}
        self.reads: list = []

    def read(self, size):
        self.reads.append(size)
        if self._broken_at is not None and self._offset >= self._broken_at:
            raise ConnectionResetError("the peer went away")
        chunk = self._body[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


def test_a_large_body_is_streamed_in_pieces_and_hashed_on_the_way(tmp_path):
    body = os.urandom(5 * MEGABYTE + 17)
    response = PiecedResponse(body)
    told: list = []

    def on_chunk(received, total, is_done=False):
        told.append((received, total, is_done))

    download = stream_to_file(
        response, tmp_path, limit=64 * MEGABYTE, on_chunk=on_chunk
    )

    assert download.size == len(body)
    assert download.sha256 == hashlib.sha256(body).hexdigest()
    assert download.head == body[:512]
    assert download.path.parent == tmp_path
    assert download.path.read_bytes() == body
    assert max(response.reads) == 64 * 1024
    assert len(response.reads) == len(body) // (64 * 1024) + 2
    assert told[-1] == (len(body), len(body), True)


def test_reading_stops_one_byte_past_the_limit(tmp_path):
    download = stream_to_file(PiecedResponse(b"x" * 1000), tmp_path, limit=100)

    assert download.size == 101


def test_a_read_that_breaks_off_leaves_no_file(tmp_path):
    response = PiecedResponse(b"x" * MEGABYTE, broken_at=256 * 1024)

    with pytest.raises(ConnectionError):
        stream_to_file(response, tmp_path, limit=64 * MEGABYTE)

    assert os.listdir(tmp_path) == []


def test_a_placed_download_is_renamed_and_a_discarded_one_is_gone(tmp_path):
    kept = stream_to_file(PiecedResponse(b"kept"), tmp_path, limit=100)
    dropped = stream_to_file(PiecedResponse(b"dropped"), tmp_path, limit=100)

    kept.place(tmp_path / "artifact")
    dropped.discard()

    assert os.listdir(tmp_path) == ["artifact"]
    assert (tmp_path / "artifact").read_bytes() == b"kept"


def test_a_file_s_digest_is_read_in_chunks(tmp_path):
    body = os.urandom(MEGABYTE + 3)
    (tmp_path / "f").write_bytes(body)

    assert file_sha256(tmp_path / "f") == hashlib.sha256(body).hexdigest()

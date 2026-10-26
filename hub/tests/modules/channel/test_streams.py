"""The hub's side of one stream on the local channel.

What these pin: a close from the hub's side writes the close record, with
its code and params, before the connection ends, so the peer reads the
result after the last byte of data.
"""

import asyncio
import socket

from neutrino_hub.modules.channel.constants import (
    CHANNEL_RECORD_CLOSE,
    CHANNEL_RECORD_DATA,
)
from neutrino_hub.modules.channel.streams import ChannelStream, decode_json, read_record


async def connected_pair():
    ours, theirs = socket.socketpair()
    reader, writer = await asyncio.open_connection(sock=ours)
    peer_reader, peer_writer = await asyncio.open_connection(sock=theirs)
    return (reader, writer), (peer_reader, peer_writer)


def test_a_close_from_the_hubs_side_writes_the_close_record_after_the_data():
    async def scenario():
        (reader, writer), (peer_reader, peer_writer) = await connected_pair()
        stream = ChannelStream(reader=reader, writer=writer, kind="package")
        await stream.send_bytes(b"body")
        await stream.close("", {"sha256": "abc"})
        records = [await read_record(peer_reader) for _ in range(3)]
        peer_writer.close()
        return stream, records

    stream, (data, close, ended) = asyncio.run(scenario())
    assert data == (CHANNEL_RECORD_DATA, b"body")
    assert close[0] == CHANNEL_RECORD_CLOSE
    assert decode_json(close[1]) == {"code": "", "params": {"sha256": "abc"}}
    assert ended is None
    assert stream.is_closed and stream.close_info == {
        "code": "",
        "params": {"sha256": "abc"},
    }


def test_a_second_close_sends_nothing_more():
    async def scenario():
        (reader, writer), (peer_reader, peer_writer) = await connected_pair()
        stream = ChannelStream(reader=reader, writer=writer, kind="package")
        await stream.close("module_artifact_missing", {})
        await stream.close("", {"sha256": "abc"})
        records = [await read_record(peer_reader) for _ in range(2)]
        peer_writer.close()
        return records

    close, ended = asyncio.run(scenario())
    assert decode_json(close[1]) == {"code": "module_artifact_missing", "params": {}}
    assert ended is None

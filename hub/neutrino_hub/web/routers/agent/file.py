"""The path window's listing of a machine's folders, over the device's agent.

The panel moves no file: a person reaches a machine's files through a
client's mount or SSH, and the path window lists folders and files to pick
one. Each request is one ``file {op: list}`` stream on the device's
session, and what the agent refuses comes back typed.
"""

import asyncio
import ntpath
import posixpath

from fastapi import APIRouter, Depends, HTTPException, status

from neutrino_hub.exceptions import AgentOfflineError
from neutrino_hub.modules.channel.constants import (
    CHANNEL_FILE_OP_LIST,
    CHANNEL_STREAM_FILE,
)
from neutrino_hub.modules.channel.streams import ChannelStream
from neutrino_hub.modules.devices.constants import DEVICE_FILE_OP_TIMEOUT_S
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.models import DeviceFileEntryView, DeviceFileListView
from neutrino_hub.web.panel_runtime import PanelRuntime

# The platform tuple's ``os`` for a machine whose paths use backslashes.
FILE_OS_WINDOWS = "windows"

router = APIRouter(
    prefix="/api/agent/file",
    tags=["file"],
    dependencies=[Depends(require_session)],
)

# Where a listing starts when the browser names no directory.
ROOT_PATH = "/"

# How each of the agent's typed codes answers on this surface.
FILE_CODE_STATUS = {
    "path_missing": status.HTTP_404_NOT_FOUND,
    "path_invalid": status.HTTP_400_BAD_REQUEST,
    "file_exists": status.HTTP_400_BAD_REQUEST,
    "write_failed": status.HTTP_400_BAD_REQUEST,
    "op_failed": status.HTTP_400_BAD_REQUEST,
}


@router.get("", response_model=DeviceFileListView)
async def list_files(
    device_id: str, path: str = "", runtime: PanelRuntime = Depends(get_runtime)
) -> DeviceFileListView:
    """List a directory on a device.

    Args:
        device_id: The device, from the query.
        path: Directory to list; empty means the root.
        runtime: The shared runtime.

    Returns:
        The resolved path, the machine's separator, and the entries,
        directories first. On Windows the root is the list of drives.
    """
    info = await _run_stream(
        runtime, device_id, {"op": CHANNEL_FILE_OP_LIST, "path": path or ROOT_PATH}
    )
    entries = [_entry_view(entry) for entry in info.get("entries") or []]
    entries.sort(key=_directories_first)
    return DeviceFileListView(
        path=str(info.get("path", path)),
        separator=str(info.get("separator") or _paths(runtime, device_id).sep),
        entries=entries,
    )


def _is_plain_name(name: str) -> bool:
    """Whether an uploaded file's name is one name and no path."""
    return bool(name) and "/" not in name and name not in (".", "..")


def _entry_view(entry: dict) -> DeviceFileEntryView:
    kind = str(entry.get("kind", ""))
    return DeviceFileEntryView(
        name=str(entry.get("name", "")),
        path=str(entry.get("path", "")),
        is_dir=kind == "dir",
        is_link=kind == "link",
        size_bytes=int(entry.get("size", 0) or 0),
        modified_at=int(entry.get("modified_at", 0) or 0),
    )


def _directories_first(entry: DeviceFileEntryView) -> tuple:
    return (not entry.is_dir, entry.name.lower())


def _paths(runtime: PanelRuntime, device_id: str):
    """The path module of the device's own form: ``ntpath`` on Windows."""
    platform = runtime.device_platform.get(device_id, {})
    if platform.get("os") == FILE_OS_WINDOWS:
        return ntpath
    return posixpath


def _joined(runtime: PanelRuntime, device_id: str, directory: str, name: str) -> str:
    """A file name joined to a directory with the device's own separator."""
    return _paths(runtime, device_id).join(directory, name)


async def _open(runtime: PanelRuntime, device_id: str, args: dict):
    """One ``file`` stream on the device, or the offline refusal."""
    try:
        return await runtime.agent_sessions.open_stream(
            device_id, CHANNEL_STREAM_FILE, args
        )
    except AgentOfflineError as error:
        raise _offline(error)


async def _run_stream(runtime: PanelRuntime, device_id: str, args: dict) -> dict:
    """Open one ``file`` stream, wait for its close, and refuse what it refused.

    Returns:
        The close's ``params``: the stream's result.
    """
    stream = await _open(runtime, device_id, args)
    try:
        info = await asyncio.wait_for(_collect(stream), DEVICE_FILE_OP_TIMEOUT_S)
    except asyncio.TimeoutError:
        await stream.close()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "agent_never_reported",
                "params": {"device": device_id},
            },
        )
    _refuse_if_coded(info)
    return dict(info.get("params") or {})


async def _collect(stream: ChannelStream) -> dict:
    """Read a stream to its close.

    Returns:
        The close, ``{"code", "params"}``.

    Raises:
        HTTPException: 409 ``agent_offline`` when the socket went away.
    """
    while True:
        item = await stream.recv()
        if item is None:
            break
    if stream.is_abandoned:
        raise _offline(AgentOfflineError(stream.kind))
    return dict(stream.close_info or {})


async def _first_bytes(stream: ChannelStream) -> bytes:
    """Wait for a download's first bytes, so a refusal answers before the body.

    Returns:
        The first bytes, for the body to start with; empty for a download
        that closed with nothing.

    Raises:
        HTTPException: The agent's typed refusal, or 409 ``agent_offline``.
    """
    item = await stream.recv()
    if item is None:
        if stream.is_abandoned:
            raise _offline(AgentOfflineError(stream.kind))
        _refuse_if_coded(stream.close_info or {})
        return b""
    return item[1]


async def _chunks(stream: ChannelStream, first: bytes = b""):
    """The stream's bytes, with the agent told to stop if the browser does."""
    try:
        if first:
            yield first
        while True:
            item = await stream.recv()
            if item is None:
                return
            yield item[1]
    finally:
        if not stream.is_closed:
            await stream.close()


def _refuse_if_coded(info: dict) -> None:
    code = str(info.get("code", "") or "")
    if code:
        _refuse(code, dict(info.get("params") or {}))


def _refuse(code: str, params: dict) -> None:
    raise HTTPException(
        status_code=FILE_CODE_STATUS.get(code, status.HTTP_409_CONFLICT),
        detail={"code": code, "params": dict(params)},
    )


def _offline(error: AgentOfflineError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": error.code, "params": dict(error.params)},
    )

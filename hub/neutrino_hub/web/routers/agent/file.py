"""File transfer between the browser and a device, over the device's agent.

The panel is the middleman: the browser never talks to the device, so this
works from anywhere the panel does. Each request is one ``file`` stream on
the device's socket, its ``op`` naming the operation, and what the agent
refuses comes back typed.
"""

import asyncio
import posixpath
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from neutrino_hub.exceptions import AgentOfflineError
from neutrino_hub.modules.channel.constants import (
    CHANNEL_FILE_OP_DIRECTORY_CREATE,
    CHANNEL_FILE_OP_DIRECTORY_DOWNLOAD,
    CHANNEL_FILE_OP_DOWNLOAD,
    CHANNEL_FILE_OP_LIST,
    CHANNEL_FILE_OP_REMOVE,
    CHANNEL_FILE_OP_RENAME,
    CHANNEL_FILE_OP_UPLOAD,
    CHANNEL_STREAM_FILE,
)
from neutrino_hub.modules.channel.sessions import ChannelStream
from neutrino_hub.modules.devices.constants import DEVICE_FILE_OP_TIMEOUT_S
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.models import (
    DeviceFileEntryView,
    DeviceFileListView,
    DeviceFilePath,
    DeviceFileRename,
)
from neutrino_hub.web.panel_runtime import PanelRuntime

router = APIRouter(
    prefix="/api/agent/file",
    tags=["file"],
    dependencies=[Depends(require_session)],
)

# Where a listing starts when the browser names no directory.
ROOT_PATH = "/"
UPLOAD_CHUNK_BYTES = 64 * 1024

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
        The resolved path and its entries, directories first.
    """
    info = await _run_stream(
        runtime, device_id, {"op": CHANNEL_FILE_OP_LIST, "path": path or ROOT_PATH}
    )
    entries = [_entry_view(entry) for entry in info.get("entries") or []]
    entries.sort(key=_directories_first)
    return DeviceFileListView(path=str(info.get("path", path)), entries=entries)


@router.get("/download")
async def download_file(
    device_id: str, path: str, runtime: PanelRuntime = Depends(get_runtime)
) -> StreamingResponse:
    """Stream one file from a device to the browser.

    Args:
        device_id: The device, from the query.
        path: The file to download.
        runtime: The shared runtime.

    Returns:
        The file as an attachment, sized only when it is done.
    """
    stream = await _open(
        runtime, device_id, {"op": CHANNEL_FILE_OP_DOWNLOAD, "path": path}
    )
    first = await _first_bytes(stream)
    name = posixpath.basename(path) or "download"
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"}
    return StreamingResponse(
        _chunks(stream, first), media_type="application/octet-stream", headers=headers
    )


@router.get("/directory/download")
async def download_dir(
    device_id: str, path: str, runtime: PanelRuntime = Depends(get_runtime)
) -> StreamingResponse:
    """Stream one directory, or one dot-named file, as a tar.gz archive.

    Browsers refuse to save a download under a hidden-file name; inside an
    archive the real name survives.

    Args:
        device_id: The device, from the query.
        path: The directory or file to pack.
        runtime: The shared runtime.

    Returns:
        The archive as an attachment, sized only when it is done.
    """
    stream = await _open(
        runtime, device_id, {"op": CHANNEL_FILE_OP_DIRECTORY_DOWNLOAD, "path": path}
    )
    first = await _first_bytes(stream)
    base = posixpath.basename(path.rstrip("/")) or "archive"
    name = base.lstrip(".") or "archive"
    return StreamingResponse(
        _chunks(stream, first),
        media_type="application/gzip",
        headers={
            "Content-Disposition": (
                f"attachment; filename*=UTF-8''{quote(name)}.tar.gz"
            )
        },
    )


@router.post("/upload")
async def upload_file(
    request: Request, runtime: PanelRuntime = Depends(get_runtime)
) -> dict:
    """Write one uploaded file into a directory on a device.

    The body is a multipart form: ``device_id`` names the device, ``path``
    the destination directory, and ``file`` is the file, which lands under
    its own name.

    Args:
        request: The incoming request.
        runtime: The shared runtime.

    Returns:
        An empty acknowledgement.

    Raises:
        HTTPException: 400 when the form lacks its three fields or the name
            is not a plain file name.
    """
    form = await request.form()
    upload = form.get("file")
    device_id = str(form.get("device_id", "") or "")
    directory = str(form.get("path", "") or "")
    name = getattr(upload, "filename", None) or ""
    if upload is None or not device_id or not directory or not _is_plain_name(name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "path_invalid", "params": {"path": name}},
        )
    size = upload.size if upload.size is not None else len(await upload.read())
    await upload.seek(0)
    stream = await _open(
        runtime,
        device_id,
        {
            "op": CHANNEL_FILE_OP_UPLOAD,
            "path": posixpath.join(directory, name),
            "size": int(size),
        },
    )
    try:
        while True:
            chunk = await upload.read(UPLOAD_CHUNK_BYTES)
            if not chunk:
                break
            await stream.send_bytes(chunk)
    except AgentOfflineError as error:
        info = stream.close_info or {}
        if info.get("code"):
            _refuse(str(info["code"]), dict(info.get("params") or {}))
        raise _offline(error)
    info = await _collect(stream)
    _refuse_if_coded(info)
    return {}


@router.post("/directory/create")
async def make_dir(
    body: DeviceFilePath, runtime: PanelRuntime = Depends(get_runtime)
) -> dict:
    """Create a directory on a device.

    Args:
        body: The device, and the directory to create.
        runtime: The shared runtime.

    Returns:
        An empty acknowledgement.
    """
    await _run_stream(
        runtime,
        body.device_id,
        {"op": CHANNEL_FILE_OP_DIRECTORY_CREATE, "path": body.path},
    )
    return {}


@router.post("/rename")
async def rename_path(
    body: DeviceFileRename,
    runtime: PanelRuntime = Depends(get_runtime),
) -> dict:
    """Rename or move a file or directory on a device.

    Args:
        body: The device, the path and its new name.
        runtime: The shared runtime.

    Returns:
        An empty acknowledgement.
    """
    await _run_stream(
        runtime,
        body.device_id,
        {"op": CHANNEL_FILE_OP_RENAME, "path": body.path, "new_path": body.new_path},
    )
    return {}


@router.post("/remove")
async def delete_path(
    body: DeviceFilePath, runtime: PanelRuntime = Depends(get_runtime)
) -> dict:
    """Delete a file, or a directory with everything in it, on a device.

    Args:
        body: The device, and the path to delete.
        runtime: The shared runtime.

    Returns:
        An empty acknowledgement.
    """
    await _run_stream(
        runtime, body.device_id, {"op": CHANNEL_FILE_OP_REMOVE, "path": body.path}
    )
    return {}


def _is_plain_name(name: str) -> bool:
    """Whether an uploaded file's name is one name and no path."""
    return bool(name) and "/" not in name and name not in (".", "..")


def _entry_view(entry: dict) -> DeviceFileEntryView:
    kind = str(entry.get("kind", ""))
    return DeviceFileEntryView(
        name=str(entry.get("name", "")),
        is_dir=kind == "dir",
        is_link=kind == "link",
        size_bytes=int(entry.get("size", 0) or 0),
        modified_at=int(entry.get("modified_at", 0) or 0),
    )


def _directories_first(entry: DeviceFileEntryView) -> tuple:
    return (not entry.is_dir, entry.name.lower())


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

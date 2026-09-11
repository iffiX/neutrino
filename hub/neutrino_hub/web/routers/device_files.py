"""File transfer between the browser and a device, over the device's agent.

The panel is the middleman: the browser never talks to the device, so this
works from anywhere the panel does. Each request is one stream on the
device's socket, and what the agent refuses comes back typed.
"""

import asyncio
import posixpath
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from neutrino_hub.exceptions import AgentOfflineError, StreamRefusedError
from neutrino_hub.modules.devices.agent_sessions import (
    STREAM_KIND_FILE_DOWNLOAD,
    STREAM_KIND_FILE_LIST,
    STREAM_KIND_FILE_OP,
    STREAM_KIND_FILE_UPLOAD,
    AgentStream,
)
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
    prefix="/api/devices",
    tags=["device_files"],
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


@router.get("/{device_id}/files", response_model=DeviceFileListView)
async def list_files(
    device_id: str, path: str = "", runtime: PanelRuntime = Depends(get_runtime)
) -> DeviceFileListView:
    """List a directory on a device.

    Args:
        device_id: The device.
        path: Directory to list; empty means the root.
        runtime: The shared runtime.

    Returns:
        The resolved path and its entries, directories first.
    """
    info = await _run_stream(
        runtime, device_id, STREAM_KIND_FILE_LIST, {"path": path or ROOT_PATH}
    )
    entries = [_entry_view(entry) for entry in info.get("entries") or []]
    entries.sort(key=_directories_first)
    return DeviceFileListView(path=str(info.get("path", path)), entries=entries)


@router.get("/{device_id}/files/download")
async def download_file(
    device_id: str, path: str, runtime: PanelRuntime = Depends(get_runtime)
) -> StreamingResponse:
    """Stream one file from a device to the browser.

    Args:
        device_id: The device.
        path: The file to download.
        runtime: The shared runtime.

    Returns:
        The file as an attachment.
    """
    stream = await _open(runtime, device_id, STREAM_KIND_FILE_DOWNLOAD, {"path": path})
    size = await _announced_size(stream)
    name = posixpath.basename(path) or "download"
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"}
    if size is not None:
        headers["Content-Length"] = str(size)
    return StreamingResponse(
        _chunks(stream), media_type="application/octet-stream", headers=headers
    )


@router.get("/{device_id}/files/download_dir")
async def download_dir(
    device_id: str, path: str, runtime: PanelRuntime = Depends(get_runtime)
) -> StreamingResponse:
    """Stream one directory, or one dot-named file, as a tar.gz archive.

    Browsers refuse to save a download under a hidden-file name; inside an
    archive the real name survives.

    Args:
        device_id: The device.
        path: The directory or file to pack.
        runtime: The shared runtime.

    Returns:
        The archive as an attachment, sized only when it is done.
    """
    stream = await _open(
        runtime,
        device_id,
        STREAM_KIND_FILE_DOWNLOAD,
        {"path": path, "is_archived": True},
    )
    base = posixpath.basename(path.rstrip("/")) or "archive"
    name = base.lstrip(".") or "archive"
    return StreamingResponse(
        _chunks(stream),
        media_type="application/gzip",
        headers={
            "Content-Disposition": (
                f"attachment; filename*=UTF-8''{quote(name)}.tar.gz"
            )
        },
    )


@router.post("/{device_id}/files/upload")
async def upload_file(
    device_id: str, request: Request, runtime: PanelRuntime = Depends(get_runtime)
) -> dict:
    """Write one uploaded file into a directory on a device.

    The body is a multipart form: ``path`` names the destination directory
    and ``file`` is the file, which lands under its own name.

    Args:
        device_id: The device.
        request: The incoming request.
        runtime: The shared runtime.

    Returns:
        An empty acknowledgement.

    Raises:
        HTTPException: 400 when the form lacks its two fields or the name
            is not a plain file name.
    """
    form = await request.form()
    upload = form.get("file")
    directory = str(form.get("path", "") or "")
    name = getattr(upload, "filename", None) or ""
    if upload is None or not directory or not _is_plain_name(name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "path_invalid", "params": {"path": name}},
        )
    size = upload.size if upload.size is not None else len(await upload.read())
    await upload.seek(0)
    stream = await _open(
        runtime,
        device_id,
        STREAM_KIND_FILE_UPLOAD,
        {"path": posixpath.join(directory, name), "size": int(size)},
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


@router.post("/{device_id}/files/mkdir")
async def make_dir(
    device_id: str, body: DeviceFilePath, runtime: PanelRuntime = Depends(get_runtime)
) -> dict:
    """Create a directory on a device.

    Args:
        device_id: The device.
        body: The directory to create.
        runtime: The shared runtime.

    Returns:
        An empty acknowledgement.
    """
    await _run_stream(
        runtime, device_id, STREAM_KIND_FILE_OP, {"op": "mkdir", "path": body.path}
    )
    return {}


@router.post("/{device_id}/files/rename")
async def rename_path(
    device_id: str,
    body: DeviceFileRename,
    runtime: PanelRuntime = Depends(get_runtime),
) -> dict:
    """Rename or move a file or directory on a device.

    Args:
        device_id: The device.
        body: The path and its new name.
        runtime: The shared runtime.

    Returns:
        An empty acknowledgement.
    """
    await _run_stream(
        runtime,
        device_id,
        STREAM_KIND_FILE_OP,
        {"op": "rename", "path": body.path, "new_path": body.new_path},
    )
    return {}


@router.post("/{device_id}/files/delete")
async def delete_path(
    device_id: str, body: DeviceFilePath, runtime: PanelRuntime = Depends(get_runtime)
) -> dict:
    """Delete a file, or a directory with everything in it, on a device.

    Args:
        device_id: The device.
        body: The path to delete.
        runtime: The shared runtime.

    Returns:
        An empty acknowledgement.
    """
    await _run_stream(
        runtime, device_id, STREAM_KIND_FILE_OP, {"op": "delete", "path": body.path}
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


async def _open(runtime: PanelRuntime, device_id: str, kind: str, args: dict):
    """One stream on the device, or the coded refusal."""
    try:
        return await runtime.agent_sessions.open_stream(device_id.lower(), kind, args)
    except AgentOfflineError as error:
        raise _offline(error)
    except StreamRefusedError as refused:
        _refuse(refused.code, refused.params)


async def _run_stream(
    runtime: PanelRuntime, device_id: str, kind: str, args: dict
) -> dict:
    """Open one stream, wait for its close, and refuse what it refused."""
    stream = await _open(runtime, device_id, kind, args)
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
    return info


async def _collect(stream: AgentStream) -> dict:
    """Read a stream to its close.

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


async def _announced_size(stream: AgentStream) -> "int | None":
    """The size a download names before its first byte, if it names one.

    Anything read past the announcement is put back for the body.
    """
    item = await stream.recv()
    if item is None:
        info = stream.close_info or {}
        if stream.is_abandoned:
            raise _offline(AgentOfflineError(stream.kind))
        _refuse_if_coded(info)
        return 0
    if item[0] == "event":
        size = item[1].get("size")
        return int(size) if size is not None else None
    stream._deliver(item)
    return None


async def _chunks(stream: AgentStream):
    """The stream's bytes, with the agent told to stop if the browser does."""
    try:
        while True:
            item = await stream.recv()
            if item is None:
                return
            if item[0] == "data":
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

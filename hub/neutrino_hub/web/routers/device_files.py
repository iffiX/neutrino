"""File transfer between the browser and a device, over the device's SSH.

The panel is the middleman: the browser never talks to the device, so this
works from anywhere the panel does — including over the overlay. Each request
opens its own SSH connection, which keeps the endpoints stateless at the cost
of a handshake per operation; on a LAN that is imperceptible.
"""

import posixpath
from urllib.parse import quote

import asyncssh
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from neutrino_hub.modules.devices.registry import DeviceRegistry, ManagedDevice
from neutrino_hub.modules.devices.ssh_ops import DeviceSshOperator, SshCredentials
from neutrino_hub.web.dependencies import require_session
from neutrino_hub.web.models import (
    DeviceFileEntryView,
    DeviceFileListView,
    DeviceFilePath,
    DeviceFileRename,
)

router = APIRouter(
    prefix="/api/devices",
    tags=["device_files"],
    dependencies=[Depends(require_session)],
)


@router.get("/{mac_address}/files", response_model=DeviceFileListView)
async def list_files(mac_address: str, path: str = "") -> DeviceFileListView:
    """List a directory on a device.

    Args:
        mac_address: The device.
        path: Directory to list; empty means the login user's home.

    Returns:
        The resolved path and its entries, directories first.
    """
    operator = _operator(mac_address)
    try:
        resolved, entries = await operator.list_dir(path)
    except (OSError, asyncssh.Error) as error:
        raise _file_error(error)
    entries.sort(key=lambda entry: (not entry.is_dir, entry.name.lower()))
    return DeviceFileListView(
        path=resolved,
        entries=[DeviceFileEntryView(**entry.__dict__) for entry in entries],
    )


@router.get("/{mac_address}/files/download")
async def download_file(mac_address: str, path: str) -> StreamingResponse:
    """Stream one file from a device to the browser.

    Args:
        mac_address: The device.
        path: The file to download.

    Returns:
        The file as an attachment.
    """
    operator = _operator(mac_address)
    try:
        download = await operator.open_download(path)
    except (OSError, asyncssh.Error) as error:
        raise _file_error(error)
    name = posixpath.basename(path) or "download"
    return StreamingResponse(
        download.chunks(),
        media_type="application/octet-stream",
        headers={
            "Content-Length": str(download.size_bytes),
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}",
        },
    )


@router.get("/{mac_address}/files/download_dir")
async def download_dir(mac_address: str, path: str) -> StreamingResponse:
    """Stream one directory — or one dot-named file — as a tar.gz archive.

    Browsers refuse to save a download under a hidden-file name, so a leading
    dot would be stripped from anything served raw. Inside an archive the real
    name survives, which is why dot-named files come through here too.

    Args:
        mac_address: The device.
        path: The directory or file to pack.

    Returns:
        The archive as an attachment, sized only when it is done.
    """
    operator = _operator(mac_address)
    try:
        download = await operator.open_archive_download(path)
    except (OSError, asyncssh.Error) as error:
        raise _file_error(error)
    base = posixpath.basename(path.rstrip("/")) or "archive"
    name = base.lstrip(".") or "archive"
    return StreamingResponse(
        download.chunks(),
        media_type="application/gzip",
        headers={
            "Content-Disposition": (
                f"attachment; filename*=UTF-8''{quote(name)}.tar.gz"
            )
        },
    )


@router.post("/{mac_address}/files/upload")
async def upload_file(
    mac_address: str, path: str, relative: str, request: Request
) -> dict:
    """Write the raw request body to a file on a device.

    The body is the file itself rather than a multipart form, so it streams
    straight through to the device without being buffered. ``relative`` may
    contain directories — that is how a folder upload arrives, one file at a
    time with its place in the tree — and missing parents are created.

    Args:
        mac_address: The device.
        path: Destination directory.
        relative: File path to create under it.
        request: The incoming request, read as a stream.

    Returns:
        An empty acknowledgement.
    """
    parts = relative.split("/")
    if len(parts) == 0 or any(part in ("", ".", "..") for part in parts):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="bad file name"
        )
    operator = _operator(mac_address)
    try:
        await operator.upload_stream(posixpath.join(path, relative), request.stream())
    except (OSError, asyncssh.Error) as error:
        raise _file_error(error)
    return {}


@router.post("/{mac_address}/files/mkdir")
async def make_dir(mac_address: str, body: DeviceFilePath) -> dict:
    """Create a directory on a device.

    Args:
        mac_address: The device.
        body: The directory to create.

    Returns:
        An empty acknowledgement.
    """
    operator = _operator(mac_address)
    try:
        await operator.make_dir(body.path)
    except (OSError, asyncssh.Error) as error:
        raise _file_error(error)
    return {}


@router.post("/{mac_address}/files/rename")
async def rename_path(mac_address: str, body: DeviceFileRename) -> dict:
    """Rename or move a file or directory on a device.

    Args:
        mac_address: The device.
        body: The path and its new name.

    Returns:
        An empty acknowledgement.
    """
    operator = _operator(mac_address)
    try:
        await operator.rename_path(body.path, body.new_path)
    except (OSError, asyncssh.Error) as error:
        raise _file_error(error)
    return {}


@router.post("/{mac_address}/files/delete")
async def delete_path(mac_address: str, body: DeviceFilePath) -> dict:
    """Delete a file, or a directory with everything in it, on a device.

    Args:
        mac_address: The device.
        body: The path to delete.

    Returns:
        An empty acknowledgement.
    """
    operator = _operator(mac_address)
    try:
        await operator.delete_path(body.path)
    except (OSError, asyncssh.Error) as error:
        raise _file_error(error)
    return {}


def _operator(mac_address: str) -> DeviceSshOperator:
    device: ManagedDevice = DeviceRegistry().get(mac_address)
    if not device.has_ssh:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="no SSH credentials for this device",
        )
    return DeviceSshOperator(credentials=SshCredentials.from_dict(device.ssh or {}))


def _file_error(error: Exception) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY, detail=str(error) or "SFTP failed"
    )

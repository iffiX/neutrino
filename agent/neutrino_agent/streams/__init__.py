"""The streams that carry bytes over the hub's socket.

A shell behind a pseudo-terminal, a shell into a container, and the file
channel: a listing, a download, an upload, and the small operations. Each
kind is one class the session opens on a thread of its own, reading the
hub's frames off its :class:`~neutrino_agent.streams.channel.StreamChannel`
and sending through it.

Every kind and what it takes and closes with:

| kind | args | close |
| --- | --- | --- |
| ``shell`` | ``{cols, rows}`` | ``{exit_code}`` |
| ``container_shell`` | ``{name}`` | ``{exit_code}`` |
| ``file_list`` | ``{path}`` | ``{path, entries}`` |
| ``file_download`` | ``{path, is_archived}`` | ``{size}`` |
| ``file_upload`` | ``{path, size}`` | ``{}`` |
| ``file_op`` | ``{op, path, new_path}`` | ``{}`` |

Every close carries ``code`` and ``params`` beside those, empty when the
stream did what it was asked. Paths are absolute; the agent is root.
"""

from neutrino_agent.streams.files import (
    FileDownloadStream,
    FileListStream,
    FileOpStream,
    FileUploadStream,
)
from neutrino_agent.streams.shell import ContainerShellStream, ShellStream

STREAM_KIND_SHELL = "shell"
STREAM_KIND_CONTAINER_SHELL = "container_shell"
STREAM_KIND_FILE_LIST = "file_list"
STREAM_KIND_FILE_DOWNLOAD = "file_download"
STREAM_KIND_FILE_UPLOAD = "file_upload"
STREAM_KIND_FILE_OP = "file_op"

# Stream kind to the class the session opens it with.
STREAM_KINDS = {
    STREAM_KIND_SHELL: ShellStream,
    STREAM_KIND_CONTAINER_SHELL: ContainerShellStream,
    STREAM_KIND_FILE_LIST: FileListStream,
    STREAM_KIND_FILE_DOWNLOAD: FileDownloadStream,
    STREAM_KIND_FILE_UPLOAD: FileUploadStream,
    STREAM_KIND_FILE_OP: FileOpStream,
}

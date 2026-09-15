"""The streams that carry bytes over the hub's socket.

Each kind is one handler the session opens on a thread of its own, reading
the hub's frames off its :class:`~neutrino_agent.streams.channel.StreamChannel`
and sending through it. A handler has ``open()``, which may raise
:class:`~neutrino_agent.exceptions.StreamRefused`, and ``run()``, which
returns ``{"code", "params"}``, what the stream closes with.

Every kind, who opens it, what it takes, and the ``params`` its close
carries when it did what it was asked:

| Opened by | kind | args | close ``params`` |
| --- | --- | --- | --- |
| hub | ``shell`` | ``{cols, rows}``, or ``{module: podman, container}`` | ``{exit_code}`` |
| hub | ``file`` | ``{op, path, ...}``; ``op`` is ``list``, ``download``, ``upload``, ``rename``, ``remove``, ``directory_create`` or ``directory_download`` | the operation's own |
| hub | ``command`` | ``{module, verb, ...args}`` | ``{exit_code, output, result}`` |
| agent | ``log`` | ``{module}``, for an install or an uninstall | ``{state}`` |
| agent | ``package`` | ``{module}``, or ``{}`` for the agent's own | ``{sha256}``, from the hub |

A close with a ``code`` is a refusal, and its ``params`` are what the
code's wording names. An unknown kind is closed ``kind_unknown``; an
unknown ``op`` or verb inside a kind is closed ``verb_unknown``. Paths are
absolute; the agent is root.
"""

from neutrino_agent.streams.files import open_file_stream
from neutrino_agent.streams.module_command import ModuleCommandStream
from neutrino_agent.streams.shell import open_shell_stream

STREAM_KIND_SHELL = "shell"
STREAM_KIND_FILE = "file"
STREAM_KIND_COMMAND = "command"
STREAM_KIND_LOG = "log"
STREAM_KIND_PACKAGE = "package"

# The kinds the hub opens, each to what serves it, called with
# ``(channel, args)``. The command kind is bound to what runs commands by
# the session that serves it.
STREAM_KINDS = {
    STREAM_KIND_SHELL: open_shell_stream,
    STREAM_KIND_FILE: open_file_stream,
    STREAM_KIND_COMMAND: ModuleCommandStream,
}

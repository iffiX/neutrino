"""The streams the hub opens to this machine, and the ones this side opens.

Each stream is one connection to the agent's transport carrying the
stream's records. Each kind the hub opens is one handler the session runs
on a thread of its own, reading the hub's records off its
:class:`~neutrino_agent.streams.channel.StreamChannel` and sending through
it. A handler has ``open()``, which may raise
:class:`~neutrino_agent.exceptions.StreamRefused`, and ``run()``, which
returns ``{"code", "params"}``, what the stream closes with. A ``connect``
the hub opens is the transport's own: it asks the agent whether the port
is published, and dials it itself.

Every kind, who opens it, what it takes, and the ``params`` its close
carries when it did what it was asked:

| Opened by | kind | args | close ``params`` |
| --- | --- | --- | --- |
| hub | ``shell`` | ``{cols, rows, account}``, with ``{session_id, is_resumed, owner, is_shared}`` for a kept shell, or ``{module: podman, container}`` | ``{exit_code}``; empty for a kept shell that runs on |
| hub | ``exec`` | ``{argv, is_tty, cols, rows, account}`` | ``{exit_code}`` |
| hub | ``file`` | ``{op: list, path}`` | ``{path, separator, entries}`` |
| hub | ``command`` | ``{module, verb, ...args}`` | ``{exit_code, output, result}`` |
| agent | ``log`` | ``{module}``, for an install or an uninstall | ``{state}`` |
| agent | ``package`` | ``{module, artifact, digest}``, or ``{}`` for the agent's own | ``{sha256, name}``, from the hub |

A close with a ``code`` is a refusal, and its ``params`` are what the
code's wording names. An unknown kind is closed ``kind_unknown``; an
unknown ``op`` or verb inside a kind is closed with its own code.
"""

from neutrino_agent.streams.exec import open_exec_stream
from neutrino_agent.streams.files import open_file_stream
from neutrino_agent.streams.module_command import ModuleCommandStream
from neutrino_agent.streams.shell import open_shell_stream

STREAM_KIND_SHELL = "shell"
STREAM_KIND_EXEC = "exec"
STREAM_KIND_FILE = "file"
STREAM_KIND_COMMAND = "command"
STREAM_KIND_LOG = "log"
STREAM_KIND_PACKAGE = "package"
STREAM_KIND_CONNECT = "connect"

# The kinds the hub opens, each to what serves it, called with
# ``(channel, args)``. The command kind is bound to what runs commands by
# the session that serves it.
STREAM_KINDS = {
    STREAM_KIND_SHELL: open_shell_stream,
    STREAM_KIND_EXEC: open_exec_stream,
    STREAM_KIND_FILE: open_file_stream,
    STREAM_KIND_COMMAND: ModuleCommandStream,
}

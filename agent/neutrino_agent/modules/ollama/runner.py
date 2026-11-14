"""Ollama as a module: the program, its service, a person's own copy, details.

The program is the publisher's release archive, which comes down a package
stream: on Linux a ``tar_zst`` unpacked through the system's ``zstd``, on
Windows a zip and on macOS a tarball, each unpacked under ``ollama/`` in the
module's directory. The system's applier runs it as a service of its own on
``127.0.0.1:11434``: a systemd unit of the account ``neutrino_ollama`` on
Linux, a LaunchDaemon of the hidden account of that name on macOS, a
scheduled task of SYSTEM's on Windows. A person's own Ollama is adopted:
on Linux its unit, which the module's Start and Stop drive and its
uninstall gives back as the first Start found it; on Windows and macOS the
app that answers on the port, which the module neither starts nor stops.
The models are the hub's to read and change through Ollama's own API; no
report carries one.

Not pure: drives Ollama through its applier.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import dataclasses
import functools
import json
import os
import subprocess
import time
import urllib.error
import urllib.request

from neutrino_agent.constants import (
    AGENT_ARTIFACT_KIND_TAR_ZST,
    AGENT_MODULE_STATE_INSTALL_FAILED,
    AGENT_STEP_ACCOUNT,
    AGENT_STEP_ARTIFACT,
    AGENT_STEP_CONFIGURE,
    AGENT_STEP_PACKAGES,
    AGENT_STEP_UNINSTALL,
    AGENT_WANT_STOPPED,
)
from neutrino_agent.exceptions import ModuleApplyError, PlatformUnsupportedError
from neutrino_agent.modules.ollama.constants import (
    OLLAMA_CODE_FOUND,
    OLLAMA_FOUND_APP,
    OLLAMA_FOUND_UNIT,
    OLLAMA_HOST,
    OLLAMA_MODELS_DIR_NAME,
    OLLAMA_NAME,
    OLLAMA_PORT,
    OLLAMA_PROBE_TIMEOUT_S,
    OLLAMA_RECORD_FIELDS,
    OLLAMA_RECORD_NAME,
    OLLAMA_START_POLL_S,
    OLLAMA_START_WAIT_S,
    OLLAMA_VERSION_MARKERS,
    OLLAMA_VERSION_PATH,
    OLLAMA_VERSION_TIMEOUT_S,
    OLLAMA_VERSION_TTL_S,
)
from neutrino_agent.modules.ollama.darwin_applier import OllamaDarwinApplier
from neutrino_agent.modules.ollama.linux_applier import OllamaLinuxApplier
from neutrino_agent.modules.ollama.windows_applier import OllamaWindowsApplier
from neutrino_agent.modules.shared.base import ModuleRunner, ModuleStep
from neutrino_agent.modules.shared.log_tail import file_tail
from neutrino_agent.modules.shared.loopback_port import (
    is_listening as loopback_is_listening,
)
from neutrino_agent.modules.shared.package import (
    joiner,
    program_stamp,
    unpack_artifact,
)
from neutrino_agent.modules.shared.record_store import InstanceRecordStore
from neutrino_agent.modules.shared.step_locks import SYSTEM_ACCOUNTS_LOCKS
from neutrino_agent.modules.shared.subprocess_run import (
    command_detail,
    units_journal,
)

# Runs the program's ``--version``; tests stand a fake in its place.
run_program = subprocess.run


def server_version(port: int = OLLAMA_PORT, timeout_s: float = OLLAMA_PROBE_TIMEOUT_S):
    """The version the server on loopback answers, None when nothing answers.

    Args:
        port: The port on ``127.0.0.1``.
        timeout_s: How long the read waits.

    Returns:
        The version ``/api/version`` names, empty when it names none; None
        when nothing answers as Ollama does.
    """
    url = f"http://{OLLAMA_HOST}:{port}{OLLAMA_VERSION_PATH}"
    try:
        with urllib.request.urlopen(url, timeout=timeout_s) as answer:
            document = json.loads(answer.read(4096).decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError):
        return None
    if not isinstance(document, dict):
        return None
    return str(document.get("version", "") or "")


def version_in(output: str) -> str:
    """The version ``ollama --version`` prints. Pure.

    Args:
        output: What it printed.

    Returns:
        The version after ``ollama version is`` or ``client version is``;
        empty when it names none.
    """
    for line in output.splitlines():
        for marker in OLLAMA_VERSION_MARKERS:
            at = line.lower().find(marker)
            if at >= 0:
                return line[at + len(marker) :].strip()
    return ""


def ollama_applier_for(platform):
    """The applier that runs Ollama on this system.

    Args:
        platform: The machine's platform.

    Returns:
        The Linux, macOS or Windows applier.

    Raises:
        PlatformUnsupportedError: On a system with none.
    """
    state_dir = platform.agent_var_dir()
    if platform.os_name == "linux":
        return OllamaLinuxApplier(state_dir=state_dir, platform=platform)
    if platform.os_name == "darwin":
        return OllamaDarwinApplier(state_dir=state_dir, platform=platform)
    if platform.os_name == "windows":
        return OllamaWindowsApplier(state_dir=state_dir, platform=platform)
    raise PlatformUnsupportedError("no Ollama here")


class OllamaModuleRunner(ModuleRunner):
    """Installs Ollama from the hub's bytes and runs it, or adopts a person's."""

    runner = OLLAMA_NAME
    name = OLLAMA_NAME

    def __init__(
        self,
        *,
        platform,
        log=print,
        publish=None,
        applier=None,
        record_dir: str = "",
        read_version=server_version,
        is_listening=None,
        clock=time.monotonic,
        sleep=time.sleep,
    ):
        """
        Args:
            platform: The machine's platform.
            log: Callable used for progress messages.
            publish: Called with ``(name, status)`` for transient states.
            applier: The system's applier; None picks the platform's own.
            record_dir: Where the module's record lives; empty is the
                module's directory.
            read_version: Called with no argument; the version the server
                on ``127.0.0.1:11434`` answers, None when nothing answers.
            is_listening: Called with no argument; whether something accepts
                a connection on ``127.0.0.1:11434`` now. None connects.
            clock: The monotonic clock the wait for the server and the
                version's age are read on.
            sleep: Waits between two looks at the server.

        Raises:
            PlatformUnsupportedError: On a system with no applier.
        """
        super().__init__(platform=platform, log=log, publish=publish)
        self._applier = applier if applier is not None else ollama_applier_for(platform)
        self._records = InstanceRecordStore(
            directory=record_dir or self.module_dir, fields=OLLAMA_RECORD_FIELDS
        )
        self._read_version = read_version
        self._is_listening = (
            is_listening
            if is_listening is not None
            else functools.partial(loopback_is_listening, OLLAMA_PORT)
        )
        self._clock = clock
        self._sleep = sleep
        # The program file the version was read from, and that version.
        self._program = None
        self._version = ""
        # The version the server last answered, None for no answer, and
        # when it was asked; asked again once it is old or the port was
        # silent since.
        self._answered = None
        self._answered_at = None

    def verify(self, recipe: dict) -> bool:
        """Whether Ollama is on the machine, the module's own or a person's.

        Only a module the state does not name is judged by it.

        Args:
            recipe: The module's recipe, empty here.

        Returns:
            True when the module's program is there, or a person's unit on
            Linux, or a person's app answers on its port on Windows and
            macOS.
        """
        return os.path.isfile(self._applier.program_path) or bool(self._found())

    def verify_environment(self) -> dict:
        """``OLLAMA_MODELS``, the module's models folder, beside the agent's own variables.

        Returns:
            The variable by name. Ollama's ``--version`` stops at a missing
            ``HOME`` unless it names the folder, and a LaunchDaemon has no
            ``HOME``.
        """
        join = joiner(self._platform.os_name)
        return {"OLLAMA_MODELS": join(self._applier.data_dir, OLLAMA_MODELS_DIR_NAME)}

    def install_steps(self, recipe: dict, steps: list) -> list:
        """The install's steps: none that installs beside a person's Ollama.

        On Linux with a person's unit the plan keeps its ``verify`` alone; on
        Windows and macOS with the publisher's app on the machine its
        ``artifact`` step refuses before anything is received.

        Args:
            recipe: The module's recipe.
            steps: The steps the method plans.

        Returns:
            The steps.
        """
        if self._applier.person_unit_path():
            return [
                step
                for step in steps
                if step.name not in (AGENT_STEP_PACKAGES, AGENT_STEP_ARTIFACT)
            ]
        app = self._applier.app_path()
        if not app:
            return steps
        return [
            (
                dataclasses.replace(
                    step,
                    run=functools.partial(_refuse_found, app),
                    failed_state=AGENT_MODULE_STATE_INSTALL_FAILED,
                )
                if step.name == AGENT_STEP_ARTIFACT
                else step
            )
            for step in steps
        ]

    def install_artifact(self, recipe: dict, artifact: dict, path: str) -> None:
        """Put the release archive in place under ``ollama/``.

        The Linux ``tar_zst`` is read through the system's ``zstd``; a zip
        and a tarball unpack as every archive does. Over a person's unit
        nothing is installed.

        Args:
            recipe: The module's recipe.
            artifact: The archive artifact.
            path: The file on local disk.

        Raises:
            ModuleApplyError: ``install_failed {detail}`` for an archive that
                cannot be unpacked.
            OSError: When the module's directory cannot be written.
            subprocess.CalledProcessError: When SELinux's label cannot be
                set on the unpack.
        """
        if self._applier.person_unit_path() and not os.path.isfile(
            self._applier.program_path
        ):
            self._log("ollama: found the machine's own Ollama, installed nothing")
            return
        if str(artifact.get("kind", "") or "") != AGENT_ARTIFACT_KIND_TAR_ZST:
            super().install_artifact(recipe, artifact, path)
            return
        placed = unpack_artifact(
            artifact,
            path,
            module_dir=self.module_dir,
            join=joiner(self._platform.os_name),
        )
        self._platform.label_programs(placed)
        self._platform.open_to_accounts(self.module_dir)

    def is_software_kept(self) -> bool:
        """Whether an uninstall leaves Ollama on the machine: a person's unit.

        Returns:
            True while a person's unit is there and the module's program
            is not.
        """
        return bool(self._applier.person_unit_path()) and not os.path.isfile(
            self._applier.program_path
        )

    def uninstall(self, recipe: dict) -> None:
        """Take the service and the program off, keeping the models.

        A person's unit is given back as the first Start found it, and
        nothing of it is removed.

        Args:
            recipe: The module's recipe.
        """
        found = self._found_unit()
        if self.is_software_kept():
            if found:
                self._applier.restore_person(found)
                self._log("ollama: gave the machine's own Ollama back as it was")
            self._forget_found_unit()
            return
        note = self._applier.uninstall()
        if note:
            self._log(f"ollama: {note}")

    def validate(self, config: dict) -> None:
        """Check a configuration: Ollama's is empty, so every one passes.

        Args:
            config: The desired configuration.
        """

    def apply(self, config: dict) -> None:
        """Write the service and run the server, at most 60 seconds until it answers.

        On a person's unit the unit is enabled and started, what it was kept
        at the first such start.

        Args:
            config: The desired configuration, empty.

        Raises:
            ModuleApplyError: ``apply_failed {detail}`` when the service
                cannot be written or the server does not answer in time.
        """
        self._apply(is_started=True)

    def apply_stopped(self, config: dict) -> None:
        """Write the service under ``stopped``, neither enabled nor started; nothing on a person's unit.

        Args:
            config: The desired configuration, empty.

        Raises:
            ModuleApplyError: As :meth:`apply` does.
        """
        self._apply(is_started=False)

    def stop(self) -> None:
        """Take the server down and keep it from starting at boot, the models in place.

        A person's unit that runs is kept as found first; one that does not
        run, with nothing kept, is left as it is.
        """
        if self.is_software_kept():
            if not self._found_unit():
                found = self._applier.person_unit_state()
                if not found.get("is_active"):
                    return
                self._keep_found_unit(found)
            self._applier.stop_person()
            return
        self._applier.stop()

    def step_locks(self, step: str) -> tuple:
        """``system_accounts`` for ``account`` and ``uninstall``.

        Args:
            step: The step's name.

        Returns:
            The step locks the module adds to the step.
        """
        if step in (AGENT_STEP_ACCOUNT, AGENT_STEP_UNINSTALL):
            return SYSTEM_ACCOUNTS_LOCKS
        return ()

    def configure_steps(self, config: dict, want: str, steps: list) -> list:
        """The server's ``account {account}`` before the core's steps, where it runs as an account of its own.

        Under ``stopped`` the ``configure`` writes the service and starts
        nothing. A person's unit takes no ``account`` step.

        Args:
            config: The configuration the task's entry carries.
            want: ``running`` or ``stopped``.
            steps: ``configure``, then ``start`` or ``stop``, as the core
                plans them.

        Returns:
            The steps.
        """
        if want == AGENT_WANT_STOPPED:
            steps = [
                (
                    dataclasses.replace(
                        step,
                        run=functools.partial(self._run_apply_stopped, dict(config)),
                    )
                    if step.name == AGENT_STEP_CONFIGURE
                    else step
                )
                for step in steps
            ]
        account = self._applier.account
        if not account or self.is_software_kept():
            return steps
        return [
            ModuleStep(
                name=AGENT_STEP_ACCOUNT,
                params={"account": account},
                run=self._run_account,
            ),
            *steps,
        ]

    def is_active(self) -> bool:
        """Whether the server runs: the module's service, a person's unit, or a person's app on its port."""
        found = self._found()
        if found == OLLAMA_FOUND_UNIT:
            return bool(self._applier.person_unit_state().get("is_active"))
        if found == OLLAMA_FOUND_APP:
            return True
        return self._applier.is_active()

    def journal_units(self) -> list:
        """The module's unit on Linux, or a person's; none elsewhere."""
        if self._found() == OLLAMA_FOUND_UNIT:
            return [self._applier.person_unit_name()]
        return self._applier.journal_units()

    def journal_text(self, lines: int) -> list:
        """The unit's journal on Linux; elsewhere the end of the server's output, then the agent's lines that name the module.

        Args:
            lines: How many lines to return at most.

        Returns:
            The lines, oldest first.
        """
        path = self._applier.output_path()
        if not path:
            return super().journal_text(lines)
        own = self._read_source(path, functools.partial(file_tail, path, lines))
        return self._with_agent_lines(own, lines)

    def details(self, recipe: dict) -> dict:
        """Whether the server answers, its port and version, and whose copy it is.

        Args:
            recipe: The module's recipe.

        Returns:
            ``{"is_running", "port", "version", "found",
            "has_package_mark"}``: ``found`` empty for the module's own
            server, ``unit`` or ``app`` for a person's, and
            ``has_package_mark`` false for a person's.
        """
        is_running = bool(self._is_listening())
        found = self._found()
        version = (self._server_version() or "") if is_running else ""
        if not version and not found:
            version = self._program_version()
        return {
            "is_running": is_running,
            "port": OLLAMA_PORT,
            "version": version,
            "found": found,
            "has_package_mark": not found,
        }

    def _found(self) -> str:
        """What a person's own Ollama is here: ``unit``, ``app``, or empty for none.

        Neither while the module's own program is on the machine, whose
        service is then what answers on the port.
        """
        if os.path.isfile(self._applier.program_path):
            return ""
        if self._applier.person_unit_path():
            return OLLAMA_FOUND_UNIT
        if (
            self._applier.is_app_system
            and self._is_listening()
            and self._server_version() is not None
        ):
            return OLLAMA_FOUND_APP
        return ""

    def _server_version(self):
        """The version the server answers, asked at most every 10 minutes while the port stays open.

        Returns:
            The version, empty when it names none; None when nothing
            answers as Ollama does.
        """
        now = self._clock()
        if (
            self._answered_at is None
            or self._answered is None
            or now - self._answered_at >= OLLAMA_VERSION_TTL_S
        ):
            self._answered = self._read_version()
            self._answered_at = now
        return self._answered

    def _apply(self, *, is_started: bool) -> None:
        """Write the service; with ``is_started`` run it and wait until it answers."""
        if self.is_software_kept():
            if not is_started:
                return
            if not self._found_unit():
                self._keep_found_unit(self._applier.person_unit_state())
            self._applier.start_person()
            self._wait_for_server()
            self._log("ollama: started the machine's own Ollama")
            return
        try:
            note = self._applier.apply(is_started=is_started)
        except (OSError, subprocess.SubprocessError) as error:
            raise ModuleApplyError(
                "apply_failed", {"detail": command_detail(error)[:500]}
            )
        if is_started:
            self._wait_for_server()
        self._log(f"ollama: {note}")

    def _run_apply_stopped(self, config: dict, context) -> None:
        """The ``configure`` step under ``stopped``."""
        self.apply_stopped(config)

    def _run_account(self, context) -> None:
        """The ``account`` step: the server's account made when it is missing, and its data directory."""
        if self._applier.ensure_account(log=self._log):
            self._log(f"ollama: gave its data to {self._applier.account}")

    def _wait_for_server(self) -> None:
        """Wait until the server answers on ``127.0.0.1:11434``.

        Raises:
            ModuleApplyError: ``apply_failed {detail}`` naming the port and
                the server's last line when the wait runs out.
        """
        deadline = self._clock() + OLLAMA_START_WAIT_S
        self._answered_at = None
        while self._read_version() is None:
            if self._clock() >= deadline:
                detail = f"ollama did not answer on {OLLAMA_HOST}:{OLLAMA_PORT}"
                said = self._last_words()
                if said:
                    detail += f": {said}"
                raise ModuleApplyError("apply_failed", {"detail": detail[:500]})
            self._sleep(OLLAMA_START_POLL_S)

    def _last_words(self) -> str:
        """The last line of the server's output: the unit's journal on Linux, the output file elsewhere."""
        path = self._applier.output_path()
        try:
            lines = (
                file_tail(path, 1) if path else units_journal(self.journal_units(), 1)
            )
        except OSError:
            return ""
        return lines[-1].strip() if lines else ""

    def _program_version(self) -> str:
        """The module's program's version, read once per program file."""
        program = program_stamp(f'"{self._applier.program_path}"')
        if program is None:
            return ""
        if program == self._program:
            return self._version
        try:
            result = run_program(
                [self._applier.program_path, "--version"],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=OLLAMA_VERSION_TIMEOUT_S,
                env={**os.environ, **self.verify_environment()},
            )
        except (OSError, subprocess.SubprocessError):
            return ""
        self._program = program
        self._version = version_in(f"{result.stdout}\n{result.stderr}")
        return self._version

    def _found_unit(self) -> dict:
        """What a person's unit was at the module's first start, empty when nothing is kept."""
        held = self._records.read(OLLAMA_RECORD_NAME).get("found_unit")
        return dict(held) if isinstance(held, dict) else {}

    def _keep_found_unit(self, found: dict) -> None:
        """Keep what a person's unit is now, before the module first moves it."""
        self._records.write(
            {
                "account": OLLAMA_RECORD_NAME,
                "found_unit": {
                    "is_enabled": bool(found.get("is_enabled")),
                    "is_active": bool(found.get("is_active")),
                },
            }
        )

    def _forget_found_unit(self) -> None:
        """Drop what was kept of a person's unit."""
        self._records.write({"account": OLLAMA_RECORD_NAME})


def _refuse_found(app: str, context) -> None:
    """The ``artifact`` step beside the publisher's app: it refuses.

    Raises:
        ModuleApplyError: ``ollama_found {path}``.
    """
    raise ModuleApplyError(OLLAMA_CODE_FOUND, {"path": app})

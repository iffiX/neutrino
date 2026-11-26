"""A Python environment: a virtual environment of a module's own Python, made with its own uv from a lock.

The lock is in the requirements format: every file of each version with its
hash, and each package's index in a ``# from`` line. The environment is made
with no seed, ``uv venv --python <python> <folder>``. The lock installs in
one part per index, each with ``uv pip install --require-hashes --no-deps
--index-url <source>``: ``<source>`` is the first ranked source of the set
the index belongs to, with the index's path below that set's source after
it, and a source that fails the part hands it to the next ranked source.
``uv pip check`` reads the environment after the parts. ``uv pip sync``
never runs. uv run as root installs wheels alone.

How each uv command runs, as root, as a service's account, or as LOCAL
SERVICE in a one-shot task, is the caller's ``run``.

Not pure: runs uv through the caller and writes the parts of a lock.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import functools
import ntpath
import os
import posixpath
import re

from neutrino_agent.exceptions import ModuleApplyError

# The comment uv's ``--emit-index-annotation`` writes under each package.
INDEX_ANNOTATION = "# from "
# The first line of a package's entry in a lock.
ENTRY_START = re.compile(r"^[A-Za-z0-9]")
# How much of uv's last words a failure names.
DETAIL_CHARS = 400
# The variables every uv run takes, beside its cache: no Python of its own
# fetched, and no configuration file of an account's or of the system's read.
UV_FIXED_VARIABLES = {"UV_PYTHON_DOWNLOADS": "never", "UV_NO_CONFIG": "1"}
# The stack uv runs with on Windows.
UV_WINDOWS_STACK = {"UV_STACK_SIZE": "16777216"}


def lock_parts(text: str) -> list:
    """A lock's packages, one part per index its ``# from`` lines name. Pure.

    Args:
        text: The lock.

    Returns:
        ``[(index, part)]`` in the order the indexes first appear: each
        part the entries of that index with their hashes, every comment
        line left out.

    Raises:
        ModuleApplyError: ``install_failed {detail}`` for an entry that
            names no index.
    """
    entries = []
    current: list = []
    for line in text.splitlines():
        if ENTRY_START.match(line):
            if current:
                entries.append(current)
            current = [line]
        elif current:
            current.append(line)
    if current:
        entries.append(current)
    parts: dict = {}
    for entry in entries:
        index = ""
        kept = []
        for line in entry:
            stripped = line.strip()
            if stripped.startswith(INDEX_ANNOTATION):
                index = stripped[len(INDEX_ANNOTATION) :].strip()
            elif stripped and not stripped.startswith("#"):
                kept.append(line)
        if not index:
            raise ModuleApplyError(
                "install_failed", {"detail": f"the lock names no index of {entry[0]}"}
            )
        parts.setdefault(index, []).append("\n".join(kept))
    return [(index, "\n".join(held) + "\n") for index, held in parts.items()]


def index_source(index: str, source_sets: dict) -> tuple:
    """The source set an index belongs to, and its path below the set's source. Pure.

    Args:
        index: An index a lock's ``# from`` line names, such as
            ``https://download.pytorch.org/whl/cpu``.
        source_sets: The state's ``source_sets``, ``{name: {sources}}``.

    Returns:
        ``(set, path)``, such as ``("pytorch", "/cpu")``; the path is empty
        for an index that is the source itself.

    Raises:
        ModuleApplyError: ``install_failed {detail}`` for an index no set's
            source holds.
    """
    wanted = index.rstrip("/")
    for name, held in sorted(source_sets.items()):
        if not isinstance(held, dict):
            continue
        for source in held.get("sources") or []:
            base = str(source).rstrip("/")
            if wanted == base or wanted.startswith(base + "/"):
                return name, wanted[len(base) :]
    raise ModuleApplyError(
        "install_failed", {"detail": f"no source set holds the index {index}"}
    )


def uv_variables(*, cache_dir: str, os_name: str) -> dict:
    """The variables a uv run takes. Pure.

    Args:
        cache_dir: uv's cache, ``uv_cache/`` beside the environment.
        os_name: ``linux``, ``darwin`` or ``windows``.

    Returns:
        ``UV_PYTHON_DOWNLOADS``, ``UV_NO_CONFIG`` and ``UV_CACHE_DIR``, and
        ``UV_STACK_SIZE`` on Windows.
    """
    variables = {**UV_FIXED_VARIABLES, "UV_CACHE_DIR": cache_dir}
    if os_name == "windows":
        variables.update(UV_WINDOWS_STACK)
    return variables


def environment_python(folder: str, os_name: str) -> str:
    """The program a virtual environment runs Python with. Pure.

    Args:
        folder: The environment.
        os_name: ``linux``, ``darwin`` or ``windows``.

    Returns:
        ``Scripts\\python.exe`` on Windows, ``bin/python`` elsewhere.
    """
    if os_name == "windows":
        return ntpath.join(folder, "Scripts", "python.exe")
    return posixpath.join(folder, "bin", "python")


def _part_rank(order: list, part: tuple) -> int:
    """Where a part installs among the others: its set's place in ``order``, the rest after. Pure."""
    set_name = part[0][0]
    return order.index(set_name) if set_name in order else len(order)


def last_words(output: str) -> str:
    """The end of what uv printed, cut short. Pure."""
    lines = [line for line in output.strip().splitlines() if line.strip()]
    return " / ".join(lines[-3:])[-DETAIL_CHARS:]


class PythonEnvironment:
    """One virtual environment of a module's own Python, made and filled with its own uv."""

    def __init__(
        self,
        *,
        uv: str,
        python: str,
        folder: str,
        os_name: str,
        run,
        rank,
        log=print,
        name: str = "",
        is_root: bool = False,
    ):
        """
        Args:
            uv: The module's uv program.
            python: The module's own Python program.
            folder: The environment.
            os_name: ``linux``, ``darwin`` or ``windows``.
            run: Called with an argument vector; runs it as the account
                the environment belongs to with uv's variables, and returns
                ``(exit_code, output)``.
            rank: Called with a source set's name; returns its sources, the
                fastest first.
            log: Called with each progress line.
            name: The module's name, which the lines carry.
            is_root: Whether uv runs as root or SYSTEM, which installs
                wheels alone.
        """
        self.folder = folder
        self._uv = uv
        self._python = python
        self._os_name = os_name
        self._run = run
        self._rank = rank
        self._log = log
        self._name = name
        self._is_root = is_root

    @property
    def python(self) -> str:
        """The environment's own Python program."""
        return environment_python(self.folder, self._os_name)

    def make(self) -> None:
        """Make the environment with no seed.

        Raises:
            ModuleApplyError: ``install_failed {detail}`` when uv refuses.
        """
        self._checked(
            [self._uv, "venv", "--python", self._python, self.folder], "uv venv"
        )

    def install(
        self,
        lock_text: str,
        *,
        parts_dir: str,
        source_sets: dict,
        set_order: tuple = (),
    ) -> None:
        """Install a lock into the environment, one part per index, then check it.

        Args:
            lock_text: The lock.
            parts_dir: A folder the running account reads and no account
                writes, where each part is written for uv.
            source_sets: The state's ``source_sets``.
            set_order: The sets whose parts install first, in this order,
                as the artifact's ``source_sets`` names them; every other
                part follows in the lock's order.

        Raises:
            ModuleApplyError: ``install_failed {detail}`` for a lock whose
                index no set holds, a part no source serves, or a check
                that fails.
            OSError: When a part cannot be written.
        """
        os.makedirs(parts_dir, mode=0o755, exist_ok=True)
        parts = [
            (index_source(index, source_sets), part)
            for index, part in lock_parts(lock_text)
        ]
        order = list(set_order)
        parts.sort(
            key=functools.partial(_part_rank, order),
        )
        for place, ((set_name, path), part) in enumerate(parts):
            part_path = os.path.join(parts_dir, f"part_{place}.txt")
            with open(part_path, "w", encoding="utf-8") as stream:
                stream.write(part)
            os.chmod(part_path, 0o644)
            self._install_part(part_path, set_name, path)
        self.check()

    def check(self) -> None:
        """``uv pip check`` over the environment.

        Raises:
            ModuleApplyError: ``install_failed {detail}`` when it fails.
        """
        self._checked(
            [self._uv, "pip", "check", "--python", self.python], "uv pip check"
        )

    def install_requirements(self, path: str, index: str) -> str:
        """Install one ``requirements.txt`` as it names its packages, with no hash.

        Args:
            path: The file.
            index: The source the packages come from.

        Returns:
            Empty when uv took it; uv's last words otherwise.
        """
        code, output = self._run(
            [
                self._uv,
                "pip",
                "install",
                "--python",
                self.python,
                "--index-url",
                index,
                "-r",
                path,
            ]
        )
        return "" if code == 0 else (last_words(output) or f"exit {code}")

    def _install_part(self, part_path: str, set_name: str, path: str) -> None:
        """Install one part from each ranked source of its set in turn, until one serves it.

        Raises:
            ModuleApplyError: ``install_failed {detail}`` when no source does.
        """
        sources = list(self._rank(set_name))
        if not sources:
            raise ModuleApplyError(
                "install_failed", {"detail": f"the state names no {set_name} source"}
            )
        detail = ""
        for source in sources:
            index = str(source).rstrip("/") + path
            self._log(f"{self._name}: uv installs {set_name} packages from {index}")
            argv = [
                self._uv,
                "pip",
                "install",
                "--python",
                self.python,
                "--require-hashes",
                "--no-deps",
                "--index-url",
                index,
                "-r",
                part_path,
            ]
            if self._is_root:
                argv.insert(3, "--no-build")
            code, output = self._run(argv)
            if code == 0:
                return
            detail = f"exit {code}: {last_words(output)}".rstrip(": ")
            self._log(f"{self._name}: uv from {index}: {detail}")
        raise ModuleApplyError("install_failed", {"detail": detail})

    def _checked(self, argv: list, what: str) -> None:
        """Run one uv command; a failure is ``install_failed`` with its last words."""
        code, output = self._run(argv)
        if code != 0:
            raise ModuleApplyError(
                "install_failed",
                {"detail": f"{what}: {last_words(output) or f'exit {code}'}"},
            )

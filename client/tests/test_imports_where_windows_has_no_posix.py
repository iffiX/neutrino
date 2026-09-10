"""Every module imports where the POSIX-only modules are missing.

Windows has no ``pty``, ``termios``, ``tty``, ``pwd``, ``grp`` or ``fcntl``;
a module-level import of one of them stops the whole client on Windows
before anything runs. The check runs in a fresh interpreter so the blocked
names cannot be satisfied from this process's cache.
"""

import pkgutil
import subprocess
import sys

import neutrino_client

POSIX_ONLY = ("pty", "termios", "tty", "pwd", "grp", "fcntl")


def test_every_module_imports_without_the_posix_only_modules():
    names = sorted(
        module.name
        for module in pkgutil.walk_packages(
            neutrino_client.__path__, neutrino_client.__name__ + "."
        )
    )
    blocked = ", ".join(f"{name!r}: None" for name in POSIX_ONLY)
    script = (
        "import sys, importlib\n"
        f"sys.modules.update({{{blocked}}})\n"
        f"for name in {names!r}:\n"
        "    importlib.import_module(name)\n"
        "print('imported', len(" + repr(names) + "))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stderr[-1500:]
    assert result.stdout.strip() == f"imported {len(names)}"

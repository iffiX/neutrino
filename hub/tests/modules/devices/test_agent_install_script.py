"""How the agent's install.sh takes its token.

The hub feeds the token over stdin with ``--token-stdin``, so what these pin
is the script's argument handling: the flag reads the first stdin line, an
empty stdin is refused, and the flag wins over a ``--token`` value. The
script's later steps need root and a device, so every run here is stopped by
its own root check.
"""

import os
import subprocess
from pathlib import Path

import pytest

INSTALL_SCRIPT = Path(__file__).resolve().parents[4] / "agent" / "install.sh"

pytestmark = pytest.mark.skipif(
    os.geteuid() == 0, reason="the script's root check is the stopping point"
)


def run_script(args: list[str], stdin_text: str = "") -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", str(INSTALL_SCRIPT), "--gateway-url", "http://gateway", *args],
        input=stdin_text,
        capture_output=True,
        text=True,
        env={**os.environ, "NO_COLOR": "1"},
    )


def test_the_script_parses():
    check = subprocess.run(
        ["bash", "-n", str(INSTALL_SCRIPT)], capture_output=True, text=True
    )
    assert check.returncode == 0, check.stderr


def test_token_stdin_reads_the_first_line():
    result = run_script(["--token-stdin"], stdin_text="a-token\n")
    assert result.returncode == 1
    assert "run this with sudo" in result.stderr


def test_token_stdin_with_nothing_on_stdin_is_refused():
    result = run_script(["--token-stdin"])
    assert result.returncode == 1
    assert "stdin carried no token" in result.stderr


def test_token_stdin_wins_over_the_token_flag():
    result = run_script(["--token", "from-argv", "--token-stdin"])
    assert result.returncode == 1
    assert "stdin carried no token" in result.stderr


def test_the_token_flag_still_works():
    result = run_script(["--token", "a-token"])
    assert result.returncode == 1
    assert "run this with sudo" in result.stderr

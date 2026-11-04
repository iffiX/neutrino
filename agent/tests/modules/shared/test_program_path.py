"""Each account's env files and marked startup lines, against a home under the test's folder.

What these pin: ``env.sh`` puts each launcher folder first and once however
often it is loaded, in every POSIX shell; ``env.fish`` says the same in
fish's words; the line goes at the end of ``.bashrc`` and of the login file
bash reads, of ``.zshrc``, of fish's ``config.fish`` or of ``.profile``; a
file that is missing is made and a missing last newline added; the second
program touches no startup file; a put-first moves the line to the end
again; and the last program let go leaves each startup file byte for byte
what it was, a link a link, ``env.sh`` gone, the Neutrino folders gone
when empty and ``~/.local`` where it was.
"""

import hashlib
import json
import os
import shutil
import subprocess

import pytest

from neutrino_agent.modules.shared.account_service import AccountEntry
from neutrino_agent.modules.shared.program_path import (
    ProgramPathApplier,
    env_fish_text,
    env_sh_text,
    startup_line,
    startup_names,
    with_line_last,
    without_lines,
)

LINE = (
    b'[ -f "$HOME/.local/share/neutrino/agent/env.sh" ] && '
    b'. "$HOME/.local/share/neutrino/agent/env.sh" # Neutrino'
)
FOLDERS = ["/s/claude_code/bin", "/s/codex/bin"]


class Platform:
    """A Linux machine whose accounts' commands run as the test's own user."""

    os_name = "linux"

    def __init__(self, root):
        self.root = str(root)
        self.asked: list = []

    def agent_var_dir(self):
        return os.path.join(self.root, "state")

    def account_process(self, account, argv):
        self.asked.append((account, list(argv)))
        return list(argv), {}


def applier_for(tmp_path, shell="/bin/bash"):
    platform = Platform(tmp_path)
    home = os.path.join(str(tmp_path), "home")
    os.makedirs(home, exist_ok=True)
    entry = AccountEntry(1000, 1000, home, shell)

    def lookup(account):
        if account != "ann":
            raise KeyError(account)
        return entry

    return ProgramPathApplier(platform=platform, lookup_account=lookup), entry


def sha(path) -> str:
    with open(path, "rb") as stream:
        return hashlib.sha256(stream.read()).hexdigest()


def tree(entry) -> str:
    return os.path.join(entry.home, ".local", "share", "neutrino", "agent")


def record(applier) -> dict:
    with open(applier.record_path, "r", encoding="utf-8") as stream:
        return json.load(stream)["accounts"]


# --- the pure parts ---


def path_after(script: str, path: str, shell: str = "sh", loads: int = 2) -> str:
    """What ``PATH`` reads after ``script`` is loaded ``loads`` times in a shell."""
    program = " ".join(['. "$1";'] * loads) + ' printf "%s" "$PATH"'
    done = subprocess.run(
        [shell, "-c", program, shell, script],
        capture_output=True,
        text=True,
        env={"PATH": path},
        timeout=30,
    )
    return done.stdout


@pytest.mark.parametrize("shell", ["sh", "bash", "zsh", "dash"])
def test_env_sh_puts_each_folder_first_once_however_often_it_is_loaded(tmp_path, shell):
    found = shutil.which(shell)
    if found is None:
        pytest.skip(f"{shell} is not installed")
    script = tmp_path / "env.sh"
    script.write_text(env_sh_text(FOLDERS))
    held = "/home/ann/.local/bin:/s/codex/bin:/usr/bin::/bin"

    assert path_after(str(script), held, found) == (
        "/s/claude_code/bin:/s/codex/bin:/home/ann/.local/bin:/usr/bin::/bin"
    )


def test_env_sh_on_an_empty_path_names_the_folders_alone(tmp_path):
    script = tmp_path / "env.sh"
    script.write_text(env_sh_text(FOLDERS))

    assert (
        path_after(str(script), "", "/bin/sh", 1) == "/s/claude_code/bin:/s/codex/bin"
    )


def test_env_sh_takes_a_folder_with_a_space(tmp_path):
    folder = "/Library/Application Support/Neutrino/agent/state/codex/bin"
    script = tmp_path / "env.sh"
    script.write_text(env_sh_text([folder]))

    assert path_after(str(script), f"/usr/bin:{folder}", "/bin/sh") == (
        f"{folder}:/usr/bin"
    )


def test_env_fish_is_pinned():
    assert env_fish_text(FOLDERS) == (
        "# Neutrino: the command line programs of this account, first on PATH.\n"
        "set -gx PATH '/s/codex/bin' (string match -v -- '/s/codex/bin' $PATH)\n"
        "set -gx PATH '/s/claude_code/bin' "
        "(string match -v -- '/s/claude_code/bin' $PATH)\n"
    )


def test_env_fish_puts_each_folder_first_once_in_fish(tmp_path):
    fish = shutil.which("fish")
    if fish is None:
        pytest.skip("fish is not installed")
    script = tmp_path / "env.fish"
    script.write_text(env_fish_text(FOLDERS))
    done = subprocess.run(
        [fish, "--no-config", "-c", f"source {script}; source {script}; echo $PATH"],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/s/codex/bin:/bin"},
        timeout=30,
    )

    assert done.stdout.split() == FOLDERS + ["/usr/bin", "/bin"]


def test_the_lines_are_pinned():
    assert startup_line("linux", is_fish=False) == LINE
    assert startup_line("darwin", is_fish=False) == (
        b'[ -f "$HOME/Library/Application Support/Neutrino/agent/env.sh" ] && '
        b'. "$HOME/Library/Application Support/Neutrino/agent/env.sh" # Neutrino'
    )
    assert startup_line("linux", is_fish=True) == (
        b'test -f "$HOME/.local/share/neutrino/agent/env.fish"; and '
        b'source "$HOME/.local/share/neutrino/agent/env.fish" # Neutrino'
    )


@pytest.mark.parametrize(
    "data",
    [b"", b"alias ll='ls -l'\n", b"no newline at the end", b"\xff\xfe raw\n\n"],
    ids=["empty", "a newline last", "no newline last", "bytes and a blank line"],
)
def test_a_line_appended_and_taken_out_leaves_the_bytes_as_they_were(data):
    text, is_added = with_line_last(data, LINE)

    assert text.endswith(LINE + b"\n")
    assert is_added is (data == b"no newline at the end")
    assert without_lines(text, (LINE,), is_added) == data


def test_a_line_is_taken_out_wherever_it_stands_and_only_it():
    data = b"a\n" + LINE + b"\nb\n" + LINE + b" # the person's\n"

    assert without_lines(data, (LINE,), False) == (
        b"a\nb\n" + LINE + b" # the person's\n"
    )


@pytest.mark.parametrize(
    "shell, present, names",
    [
        ("/bin/bash", {".bash_profile", ".profile"}, [".bashrc", ".bash_profile"]),
        ("/bin/bash", {".bash_login", ".profile"}, [".bashrc", ".bash_login"]),
        ("/usr/bin/bash", {".profile"}, [".bashrc", ".profile"]),
        ("/bin/bash", set(), [".bashrc", ".profile"]),
        ("/bin/zsh", {".profile"}, [".zshrc"]),
        ("/usr/bin/fish", set(), [".config/fish/config.fish"]),
        ("/bin/dash", set(), [".profile"]),
        ("", set(), [".profile"]),
    ],
)
def test_each_login_shell_reads_its_own_startup_files(shell, present, names):
    assert startup_names(shell, present) == names


# --- an account's files ---


def test_the_first_program_writes_env_sh_and_the_line_and_the_second_touches_no_startup_file(
    tmp_path,
):
    applier, entry = applier_for(tmp_path)
    bashrc = os.path.join(entry.home, ".bashrc")
    profile = os.path.join(entry.home, ".profile")
    with open(bashrc, "wb") as stream:
        stream.write(b"alias ll='ls -l'\n")
    with open(profile, "wb") as stream:
        stream.write(b"umask 022")

    applier.set_module("ann", entry, "codex", is_put_first=True)

    with open(bashrc, "rb") as stream:
        assert stream.read() == b"alias ll='ls -l'\n" + LINE + b"\n"
    with open(profile, "rb") as stream:
        assert stream.read() == b"umask 022\n" + LINE + b"\n"
    env = os.path.join(tree(entry), "env.sh")
    state = str(tmp_path / "state")
    with open(env, "r", encoding="utf-8") as stream:
        assert stream.read() == env_sh_text([f"{state}/codex/bin"])
    before = (sha(bashrc), sha(profile))

    applier.set_module("ann", entry, "claude_code", is_put_first=False)

    assert (sha(bashrc), sha(profile)) == before
    with open(env, "r", encoding="utf-8") as stream:
        assert stream.read() == env_sh_text(
            [f"{state}/claude_code/bin", f"{state}/codex/bin"]
        )
    held = record(applier)["ann"]
    assert held["modules"] == ["claude_code", "codex"]
    assert held["files"] == {
        bashrc: {"is_made": False, "is_newline_added": False},
        profile: {"is_made": False, "is_newline_added": True},
    }
    assert os.stat(applier.record_path).st_mode & 0o777 == 0o600


def test_the_last_program_let_go_leaves_every_file_as_it_was(tmp_path):
    applier, entry = applier_for(tmp_path)
    bashrc = os.path.join(entry.home, ".bashrc")
    with open(bashrc, "wb") as stream:
        stream.write(b"export A=1")
    os.makedirs(os.path.join(entry.home, ".local", "bin"))
    before = sha(bashrc)
    applier.set_module("ann", entry, "codex", is_put_first=True)
    applier.set_module("ann", entry, "claude_code", is_put_first=False)

    applier.drop_module("ann", "codex")
    assert sha(bashrc) != before
    applier.drop_module("ann", "claude_code")

    assert sha(bashrc) == before
    assert not os.path.exists(os.path.join(entry.home, ".profile"))
    assert not os.path.exists(os.path.join(entry.home, ".local", "share", "neutrino"))
    assert os.path.isdir(os.path.join(entry.home, ".local", "share"))
    assert os.listdir(os.path.join(entry.home, ".local", "bin")) == []
    assert record(applier) == {}


def test_a_neutrino_folder_holding_another_module_s_files_stays(tmp_path):
    applier, entry = applier_for(tmp_path)
    os.makedirs(os.path.join(tree(entry), "cloudcli"))
    applier.set_module("ann", entry, "codex", is_put_first=True)

    applier.drop_module("ann", "codex")

    assert os.listdir(tree(entry)) == ["cloudcli"]


def test_a_startup_file_that_is_a_link_stays_a_link(tmp_path):
    applier, entry = applier_for(tmp_path)
    dotfiles = tmp_path / "dotfiles"
    dotfiles.mkdir()
    (dotfiles / "bashrc").write_bytes(b"set -o vi\n")
    os.symlink(str(dotfiles / "bashrc"), os.path.join(entry.home, ".bashrc"))

    applier.set_module("ann", entry, "codex", is_put_first=True)
    assert (dotfiles / "bashrc").read_bytes() == b"set -o vi\n" + LINE + b"\n"
    applier.drop_module("ann", "codex")

    assert os.path.islink(os.path.join(entry.home, ".bashrc"))
    assert (dotfiles / "bashrc").read_bytes() == b"set -o vi\n"


def test_put_first_moves_the_line_after_one_the_person_added(tmp_path):
    applier, entry = applier_for(tmp_path, shell="/bin/zsh")
    zshrc = os.path.join(entry.home, ".zshrc")
    applier.set_module("ann", entry, "codex", is_put_first=True)
    with open(zshrc, "ab") as stream:
        stream.write(b'export PATH="$HOME/.local/bin:$PATH"\n')

    applier.set_module("ann", entry, "codex", is_put_first=False)
    with open(zshrc, "rb") as stream:
        assert stream.read().endswith(b'$PATH"\n')
    applier.set_module("ann", entry, "codex", is_put_first=True)

    with open(zshrc, "rb") as stream:
        assert stream.read() == b'export PATH="$HOME/.local/bin:$PATH"\n' + LINE + b"\n"
    assert record(applier)["ann"]["files"] == {
        zshrc: {"is_made": True, "is_newline_added": False}
    }


def test_a_fish_account_gets_env_fish_and_a_line_in_config_fish(tmp_path):
    applier, entry = applier_for(tmp_path, shell="/usr/bin/fish")

    applier.set_module("ann", entry, "claude_code", is_put_first=True)

    config = os.path.join(entry.home, ".config", "fish", "config.fish")
    with open(config, "rb") as stream:
        assert stream.read() == startup_line("linux", is_fish=True) + b"\n"
    state = str(tmp_path / "state")
    with open(os.path.join(tree(entry), "env.fish"), "r", encoding="utf-8") as stream:
        assert stream.read() == env_fish_text([f"{state}/claude_code/bin"])

    applier.drop_module("ann", "claude_code")

    assert not os.path.exists(config)
    assert os.path.isdir(os.path.join(entry.home, ".config", "fish"))


def test_every_file_is_read_and_written_as_the_account(tmp_path):
    applier, entry = applier_for(tmp_path)

    applier.set_module("ann", entry, "codex", is_put_first=True)

    asked = applier._platform.asked
    assert asked and all(account == "ann" for account, _argv in asked)
    assert all(argv[0] == "/bin/sh" for _account, argv in asked)


def test_the_stamps_name_each_startup_file_and_env_file(tmp_path):
    applier, entry = applier_for(tmp_path, shell="/bin/zsh")
    assert applier.stamps("ann") == {}
    applier.set_module("ann", entry, "codex", is_put_first=True)

    stamps = applier.stamps("ann")

    assert sorted(stamps) == sorted(
        [os.path.join(entry.home, ".zshrc"), os.path.join(tree(entry), "env.sh")]
    )
    assert all(stamp is not None for stamp in stamps.values())


def test_an_account_gone_from_the_machine_is_dropped_from_the_record(tmp_path):
    applier, entry = applier_for(tmp_path)
    applier.set_module("ann", entry, "codex", is_put_first=True)
    held = record(applier)
    held["bob"] = held.pop("ann")
    with open(applier.record_path, "w", encoding="utf-8") as stream:
        json.dump({"accounts": held}, stream)

    assert applier.drop_module("bob", "codex") == [
        "bob is gone, its PATH record dropped"
    ]
    assert record(applier) == {}

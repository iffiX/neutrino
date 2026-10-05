"""RustDesk's settings files: what is written, and what is kept.

Nothing here reaches a real RustDesk. What is pinned is that a write keeps
what it did not come to change and whose the file was, that the options
send nothing to a public server, and that the permanent password lands as
plain text in ``RustDesk.toml``.
"""

import os

import pytest

from neutrino_agent.exceptions import InstallError
from neutrino_agent.modules import rustdesk
from neutrino_agent.modules.remote_desktop.constants import (
    REMOTE_DESKTOP_DIRECT_PORT,
    REMOTE_DESKTOP_OPTIONS,
)
from neutrino_agent.modules.rustdesk import (
    config_paths,
    read_password,
    render_config,
    render_password,
    would_change,
    write_config,
    write_password,
)

# --- the options ---


def test_the_rendezvous_and_relay_servers_are_the_machines_own_loopback():
    """An empty value means upstream's public server."""
    options = dict(REMOTE_DESKTOP_OPTIONS)

    assert options["custom-rendezvous-server"] == "127.0.0.1"
    assert options["relay-server"] == "127.0.0.1"
    assert options["direct-server"] == "Y"
    assert options["allow-auto-update"] == "N"


def test_the_direct_port_is_the_one_a_bare_address_is_dialled_at():
    assert REMOTE_DESKTOP_DIRECT_PORT == 21118
    assert dict(REMOTE_DESKTOP_OPTIONS)["direct-access-port"] == "21118"


def test_the_options_close_what_this_hub_does_not_publish():
    options = dict(REMOTE_DESKTOP_OPTIONS)

    assert options["enable-tunnel"] == "N"
    assert options["enable-audio"] == "N"
    assert options["verification-method"] == "use-permanent-password"


def test_a_rendered_file_carries_every_option_under_one_table():
    rendered = render_config("", REMOTE_DESKTOP_OPTIONS)

    assert rendered.count("[options]") == 1
    for key, value in REMOTE_DESKTOP_OPTIONS:
        assert f"{key} = '{value}'" in rendered


def test_rendering_keeps_the_machines_own_state_above_the_options():
    existing = "rendezvous_server = 'x'\nnat_type = 1\n\n[options]\nkey = 'old'\n"

    rendered = render_config(existing, (("key", "new"),))

    assert "rendezvous_server = 'x'" in rendered
    assert "nat_type = 1" in rendered
    assert "key = 'new'" in rendered
    assert "key = 'old'" not in rendered


def test_rendering_keeps_an_option_it_was_not_asked_about():
    existing = "[options]\nkept-by-rustdesk = 'yes'\ndirect-server = 'N'\n"

    rendered = render_config(existing, (("direct-server", "Y"),))

    assert "kept-by-rustdesk = 'yes'" in rendered
    assert "direct-server = 'Y'" in rendered
    assert "direct-server = 'N'" not in rendered


def test_a_written_file_is_whole_and_readable_again(tmp_path):
    path = str(tmp_path / "config" / "RustDesk2.toml")

    write_config(path, REMOTE_DESKTOP_OPTIONS)
    write_config(path, REMOTE_DESKTOP_OPTIONS)

    text = open(path, encoding="utf-8").read()
    assert text.count("[options]") == 1
    assert text.count("direct-server = 'Y'") == 1
    assert not os.path.exists(f"{path}.tmp")


def test_a_write_says_whether_the_file_is_not_what_it_was(tmp_path):
    path = tmp_path / "RustDesk2.toml"

    assert write_config(str(path), REMOTE_DESKTOP_OPTIONS) is True
    assert write_config(str(path), REMOTE_DESKTOP_OPTIONS) is False


def test_a_file_that_cannot_be_written_is_a_typed_refusal(tmp_path):
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory")

    with pytest.raises(InstallError):
        write_config(str(blocker / "config" / "RustDesk2.toml"), (("a", "b"),))


def test_every_path_the_service_and_the_session_read(monkeypatch):
    monkeypatch.setattr(rustdesk.sys, "platform", "linux")

    assert config_paths("/home/pat") == [
        "/root/.config/rustdesk/RustDesk2.toml",
        "/home/pat/.config/rustdesk/RustDesk2.toml",
    ]
    assert config_paths("") == ["/root/.config/rustdesk/RustDesk2.toml"]


def test_on_windows_no_linux_path_is_named(monkeypatch):
    monkeypatch.setattr(rustdesk.sys, "platform", "win32")

    assert config_paths("C:\\Users\\pat") == []


# --- the password ---


def test_the_password_replaces_the_line_rustdesk_wrote():
    existing = "enc_id = 'x'\npassword = '00abc'\nsalt = 's'\n\n[keys]\nk = 1\n"

    rendered = render_password(existing, "seat-pass")

    assert "password = 'seat-pass'" in rendered
    assert "00abc" not in rendered
    assert "enc_id = 'x'" in rendered
    assert "[keys]" in rendered


def test_a_password_goes_above_the_first_table_when_none_was_there():
    rendered = render_password("enc_id = 'x'\n[keys]\nk = 1\n", "p")

    lines = rendered.splitlines()
    assert lines.index("password = 'p'") < lines.index("[keys]")


def test_a_password_with_a_quote_is_a_basic_string():
    rendered = render_password("", "it's")

    assert 'password = "it\'s"' in rendered


def test_the_written_password_reads_back(tmp_path):
    path = str(tmp_path / "RustDesk.toml")

    assert write_password(path, "seat-pass") is True
    assert write_password(path, "seat-pass") is False
    assert read_password(path) == "seat-pass"


def test_a_password_under_a_table_is_not_read(tmp_path):
    path = tmp_path / "RustDesk.toml"
    path.write_text("[options]\npassword = 'no'\n", encoding="utf-8")

    assert read_password(str(path)) == ""


def test_a_missing_file_has_no_password(tmp_path):
    assert read_password(str(tmp_path / "absent.toml")) == ""


def test_whether_a_write_would_change_a_file(tmp_path):
    path = tmp_path / "RustDesk.toml"

    assert would_change(str(path), lambda existing: "x\n") is True
    path.write_text("x\n", encoding="utf-8")
    assert would_change(str(path), lambda existing: "x\n") is False
    assert would_change(str(path), lambda existing: "y\n") is True


# --- a session's settings stay that person's own ---


def test_a_rewrite_keeps_the_owner_and_mode_the_file_had(monkeypatch, tmp_path):
    """RustDesk runs as the person at the screen and writes its Wayland
    screen-capture permission into this file. Left owned by root it cannot,
    and that permission dialog returns on every connection."""
    path = tmp_path / "RustDesk2.toml"
    path.write_text("[options]\nwayland-restore-token = 'tok'\n", encoding="utf-8")
    chowned, chmodded = [], []
    monkeypatch.setattr(rustdesk, "_owner_of", lambda target: (1000, 1000, 0o600))
    monkeypatch.setattr(
        rustdesk.os, "chown", lambda target, uid, gid: chowned.append((uid, gid))
    )
    monkeypatch.setattr(
        rustdesk.os, "chmod", lambda target, mode: chmodded.append(mode)
    )

    rustdesk.write_config(str(path), REMOTE_DESKTOP_OPTIONS)

    assert chowned == [(1000, 1000)]
    assert chmodded == [0o600]
    assert "tok" in path.read_text(encoding="utf-8")


def test_an_existing_file_answers_for_its_own_owner(tmp_path):
    path = tmp_path / "RustDesk2.toml"
    path.write_text("", encoding="utf-8")
    path.chmod(0o600)

    assert rustdesk._owner_of(str(path)) == (os.getuid(), os.getgid(), 0o600)


def test_a_fresh_file_takes_the_home_it_is_under(tmp_path):
    home = tmp_path / "pat"
    (home / ".config" / "rustdesk").mkdir(parents=True)

    owner = rustdesk._owner_of(str(home / ".config" / "rustdesk" / "RustDesk2.toml"))

    assert owner == (os.getuid(), os.getgid(), 0o644)


def test_a_file_under_nothing_but_root_is_left_to_root(monkeypatch):
    class _Root:
        st_uid = 0
        st_gid = 0
        st_mode = 0o755

    monkeypatch.setattr(
        rustdesk,
        "_stat",
        lambda target: None if target.endswith(".toml") else _Root(),
    )

    assert rustdesk._owner_of("/root/.config/rustdesk/RustDesk2.toml") is None


def test_a_rewrite_keeps_going_where_ownership_cannot_be_set(monkeypatch, tmp_path):
    path = tmp_path / "RustDesk2.toml"
    path.write_text("[options]\n")
    monkeypatch.delattr(rustdesk.os, "chown")

    assert write_config(str(path), (("direct-server", "Y"),)) is True
    assert "direct-server = 'Y'" in path.read_text()

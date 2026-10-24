"""RustDesk's settings files: what is written, and what is kept.

Nothing here reaches a real RustDesk. What is pinned is that a write keeps
what it did not come to change and whose the file was, that the options
send nothing to a public server, and that the permanent password lands as
plain text in ``RustDesk.toml``.
"""

import os

import pytest

from neutrino_agent.exceptions import InstallError
from neutrino_agent.modules.remote_desktop.rdp import rustdesk
from neutrino_agent.modules.remote_desktop.constants import (
    REMOTE_DESKTOP_DIRECT_PORT,
    REMOTE_DESKTOP_OPTIONS,
)
from neutrino_agent.modules.remote_desktop.rdp.rustdesk import (
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


class _Owned:
    """A stat that names another owner."""

    def __init__(self, uid, gid, mode):
        self.st_uid = uid
        self.st_gid = gid
        self.st_mode = mode


def _owners(monkeypatch, owners):
    """Make ``chown`` record into ``owners`` and ``_stat`` read from it, so a
    folder given an owner reads back as that owner's."""
    real_stat = rustdesk._stat
    chowned = []

    def stat(target):
        found = real_stat(target)
        if found is None or target not in owners:
            return found
        return _Owned(owners[target][0], owners[target][1], found.st_mode)

    def chown(target, uid, gid):
        chowned.append((target, uid, gid))
        owners[target] = (uid, gid)

    monkeypatch.setattr(rustdesk, "_stat", stat)
    monkeypatch.setattr(rustdesk.os, "chown", chown)
    return chowned


def test_each_folder_made_under_a_home_is_given_the_homes_owner(monkeypatch, tmp_path):
    """RustDesk running as that person writes its own files into these
    folders; one left to root fails to store its configuration."""
    home = tmp_path / "pat"
    home.mkdir()
    chowned = _owners(monkeypatch, {str(home): (4242, 4343)})
    path = home / ".config" / "rustdesk" / "RustDesk2.toml"

    rustdesk.write_settings(str(path), lambda existing: "[options]\n", str(home))

    assert chowned == [
        (str(home / ".config"), 4242, 4343),
        (str(home / ".config" / "rustdesk"), 4242, 4343),
        (f"{path}.tmp", 4242, 4343),
    ]
    assert path.is_file()


def test_a_folder_that_was_there_keeps_its_owner(monkeypatch, tmp_path):
    home = tmp_path / "pat"
    (home / ".config").mkdir(parents=True)
    chowned = _owners(monkeypatch, {str(home): (4242, 4343)})
    path = home / ".config" / "rustdesk" / "RustDesk2.toml"

    rustdesk.write_settings(str(path), lambda existing: "[options]\n", str(home))

    folders = [target for target, _, _ in chowned if not target.endswith(".tmp")]
    assert folders == [str(home / ".config" / "rustdesk")]


def test_folders_outside_the_home_are_made_as_this_process(monkeypatch, tmp_path):
    home = tmp_path / "pat"
    home.mkdir()
    chowned = _owners(monkeypatch, {str(home): (4242, 4343)})
    path = tmp_path / "root" / ".config" / "rustdesk" / "RustDesk.toml"

    rustdesk.write_settings(str(path), lambda existing: "id = ''\n", str(home))
    rustdesk.write_password(str(path), "seat-pass")

    assert [target for target, _, _ in chowned if not target.endswith(".tmp")] == []
    assert "seat-pass" in path.read_text()


def _lstat_owners(monkeypatch, uids):
    """Make ``_lstat`` report the given owner of each named folder."""
    real_lstat = rustdesk._lstat

    def lstat(target):
        found = real_lstat(target)
        if found is None or target not in uids:
            return found
        return _Owned(uids[target], uids[target], found.st_mode)

    monkeypatch.setattr(rustdesk, "_lstat", lstat)


def _seat_folders(tmp_path):
    home = tmp_path / "pat"
    settings = home / ".config" / "rustdesk"
    settings.mkdir(parents=True)
    return home, home / ".config", settings


def test_folders_root_owns_under_a_home_are_given_to_its_owner(monkeypatch, tmp_path):
    """A machine an earlier agent shared has the seat's folders made as
    root."""
    home, config, settings = _seat_folders(tmp_path)
    chowned = _owners(monkeypatch, {str(home): (4242, 4343)})
    _lstat_owners(monkeypatch, {str(config): 0, str(settings): 0})

    given = rustdesk.give_back_dirs(str(settings), str(home))

    assert given == [str(config), str(settings)]
    assert chowned == [(str(config), 4242, 4343), (str(settings), 4242, 4343)]


def test_writing_into_a_settings_folder_root_owns_gives_it_back(monkeypatch, tmp_path):
    home, config, settings = _seat_folders(tmp_path)
    chowned = _owners(monkeypatch, {str(home): (4242, 4343)})
    _lstat_owners(monkeypatch, {str(settings): 0})

    rustdesk.write_settings(
        str(settings / "RustDesk2.toml"), lambda existing: "[options]\n", str(home)
    )

    assert chowned == [
        (str(settings), 4242, 4343),
        (str(settings / "RustDesk2.toml.tmp"), 4242, 4343),
    ]


def test_a_folder_another_person_owns_keeps_its_owner(monkeypatch, tmp_path):
    home, config, settings = _seat_folders(tmp_path)
    chowned = _owners(monkeypatch, {str(home): (4242, 4343)})
    _lstat_owners(monkeypatch, {str(config): 1001, str(settings): 0})

    assert rustdesk.give_back_dirs(str(settings), str(home)) == [str(settings)]
    assert [target for target, _, _ in chowned] == [str(settings)]


def test_under_roots_own_home_nothing_is_given(monkeypatch, tmp_path):
    home, config, settings = _seat_folders(tmp_path)
    chowned = _owners(monkeypatch, {str(home): (0, 0)})
    _lstat_owners(monkeypatch, {str(config): 0, str(settings): 0})

    assert rustdesk.give_back_dirs(str(settings), str(home)) == []
    assert rustdesk.give_back_dirs(str(tmp_path / "elsewhere"), str(home)) == []
    assert chowned == []


def test_a_symbolic_link_on_the_way_is_not_given(monkeypatch, tmp_path):
    home = tmp_path / "pat"
    home.mkdir()
    (tmp_path / "dotfiles" / "rustdesk").mkdir(parents=True)
    (home / ".config").symlink_to(tmp_path / "dotfiles")
    settings = home / ".config" / "rustdesk"
    _owners(monkeypatch, {str(home): (4242, 4343)})
    _lstat_owners(monkeypatch, {str(home / ".config"): 0, str(settings): 0})

    assert rustdesk.give_back_dirs(str(settings), str(home)) == [str(settings)]


# --- what RustDesk itself writes into RustDesk.toml ---

# Sealed by libsodium's crypto_secretbox_easy as RustDesk 1.4.9 seals: the
# format byte 1, the nonce 01 02 .. 18, then the box, keyed by MACHINE_ID.
MACHINE_ID = "0123456789abcdef0123456789abcdef"
SEALED_SEAT_PASS = "00AQECAwQFBgcICQoLDA0ODxAREhMUFRYXGG2fyudFFP3NcbnInbL1TKs2qvqEDMktoUs="  # scan: allow
SEALED_SOMEBODY_ELSE = "00AQECAwQFBgcICQoLDA0ODxAREhMUFRYXGBSElnFzz9I+Uc3wfcpDZGI2oPaVQ9YoqxVyJktV"  # scan: allow
# The older form: the box alone under a zero nonce.
SEALED_SEAT_PASS_LEGACY = "00bBoLokP5NnGNORK88bt24/ZYHbDqGSdFzA=="  # scan: allow
# A Mac's id is 36 characters; RustDesk keys with its first 32.
MAC_ID = "564D0000-1111-2222-3333-444455556666"
SEALED_ON_A_MAC = "00AQECAwQFBgcICQoLDA0ODxAREhMUFRYXGLoT23bUpRkua1oi2WoGNnWxo8xQXw7dj7o="  # scan: allow
# A short id is padded with zeros to 32 bytes.
SEALED_UNDER_ABC = "00AQECAwQFBgcICQoLDA0ODxAREhMUFRYXGNK4bFJhtgwmuwHbhe9/CjmUmdOeRJg57Uk="  # scan: allow


def rustdesk_toml(password="", *, enc_id="00AQIDBAUGBwgJCgsMDQ4PEBES", pairs=True):
    """``RustDesk.toml`` as RustDesk writes it, its arrays one item a line."""
    lines = [f"enc_id = '{enc_id}'", f"password = '{password}'", "salt = 'abc'"]
    if pairs:
        lines += ["key_pair = [", "    [", "        12,", "        34,", "    ],"]
        lines += ["    [", "        56,", "    ],", "]"]
    else:
        lines += ["key_pair = [", "    [],", "    [],", "]"]
    lines += ["key_confirmed = false", "", "[keys_confirmed]"]
    return "\n".join(lines) + "\n"


def test_the_values_are_read_whole_across_lines(tmp_path):
    path = tmp_path / "RustDesk.toml"
    path.write_text(rustdesk_toml("pw") + "password_under_a_table = 'no'\n")

    values = rustdesk.read_values(str(path))

    assert values["password"] == "pw"
    assert values["salt"] == "abc"
    assert "56" in values["key_pair"]
    assert values["key_confirmed"] == "false"
    assert "password_under_a_table" not in values


def test_a_file_the_agent_wrote_alone_holds_no_identity(tmp_path):
    path = tmp_path / "RustDesk.toml"
    write_password(str(path), "seat-pass")

    assert rustdesk.has_identity(str(path)) is False
    assert rustdesk.has_identity(str(tmp_path / "absent.toml")) is False


def test_an_id_and_a_key_pair_are_the_identity(tmp_path):
    path = tmp_path / "RustDesk.toml"

    path.write_text(rustdesk_toml(pairs=False))
    assert rustdesk.has_identity(str(path)) is False

    path.write_text(rustdesk_toml(enc_id=""))
    assert rustdesk.has_identity(str(path)) is False

    path.write_text(rustdesk_toml())
    assert rustdesk.has_identity(str(path)) is True

    path.write_text("id = '123456789'\nkey_pair = [[1, 2], [3]]\n")
    assert rustdesk.has_identity(str(path)) is True


@pytest.mark.parametrize(
    "value, machine_id, opened",
    [
        (SEALED_SEAT_PASS, MACHINE_ID, "seat-pass"),
        (SEALED_SOMEBODY_ELSE, MACHINE_ID, "somebody-else"),
        (SEALED_SEAT_PASS_LEGACY, MACHINE_ID, "seat-pass"),
        (SEALED_ON_A_MAC, MAC_ID, "seat-pass"),
        (SEALED_UNDER_ABC, "abc", "seat-pass"),
        (SEALED_SEAT_PASS, "another-machine-id", None),
        ("seat-pass", MACHINE_ID, None),
    ],
)
def test_a_sealed_value_opens_with_the_machines_id(value, machine_id, opened):
    assert rustdesk.open_sealed(value, machine_id) == opened


def test_a_plain_password_that_starts_like_a_sealed_one_is_plain():
    """The hub's seat passwords are 22 letters and digits; RustDesk reads
    one starting with 00 as plain text too."""
    assert rustdesk.is_sealed("00abcdefghijKLMNOPQRST") is False
    assert rustdesk.is_sealed(SEALED_SEAT_PASS) is True


def test_the_stored_password_is_read_as_a_peer_types_it(tmp_path):
    path = tmp_path / "RustDesk.toml"

    path.write_text(rustdesk_toml(SEALED_SEAT_PASS))
    assert rustdesk.stored_password(str(path), lambda: MACHINE_ID) == "seat-pass"

    path.write_text(rustdesk_toml(""))
    assert rustdesk.stored_password(str(path), lambda: MACHINE_ID) == ""

    path.write_text(rustdesk_toml(SEALED_SEAT_PASS))
    assert rustdesk.stored_password(str(path), lambda: "another") is None

    assert rustdesk.stored_password(str(tmp_path / "absent"), lambda: "") == ""


def test_a_plain_password_needs_no_machine_id(tmp_path):
    path = tmp_path / "RustDesk.toml"
    write_password(str(path), "seat-pass")

    def unreadable():
        raise AssertionError("the machine id was read")

    assert rustdesk.stored_password(str(path), unreadable) == "seat-pass"


def test_a_password_rewrite_keeps_what_rustdesk_wrote(tmp_path):
    path = tmp_path / "RustDesk.toml"
    path.write_text(rustdesk_toml(""))

    write_password(str(path), "seat-pass")

    assert rustdesk.has_identity(str(path)) is True
    assert rustdesk.stored_password(str(path), lambda: MACHINE_ID) == "seat-pass"
    assert "[keys_confirmed]" in path.read_text()

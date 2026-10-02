"""``nhub unlock``: the lockout file on every system, fail2ban on Linux."""

from neutrino_hub.cli import unlock


def test_linux_clears_the_lockout_and_the_ssh_bans(monkeypatch, tmp_path):
    lockout = tmp_path / "login_lockout.json"
    lockout.write_text("{}")
    ran = []
    monkeypatch.setattr(unlock, "WEB_LOGIN_LOCKOUT_STATE_PATH", lockout)
    monkeypatch.setattr(unlock, "run", lambda command, **k: ran.append(command))
    monkeypatch.setattr(unlock.sys, "argv", ["nhub unlock"])
    monkeypatch.setattr("os.geteuid", lambda: 0)

    assert unlock.main() == 0
    assert not lockout.exists()
    assert ran == [["fail2ban-client", "unban", "--all"]]


def test_macos_has_no_fail2ban_to_ask(monkeypatch, tmp_path):
    lockout = tmp_path / "login_lockout.json"
    lockout.write_text("{}")
    monkeypatch.setattr(unlock, "WEB_LOGIN_LOCKOUT_STATE_PATH", lockout)
    monkeypatch.setattr(
        unlock, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError)
    )
    monkeypatch.setattr(unlock.sys, "argv", ["nhub unlock"])
    monkeypatch.setattr(unlock.sys, "platform", "darwin")
    monkeypatch.setattr("os.geteuid", lambda: 0)

    assert unlock.main() == 0
    assert not lockout.exists()


def test_an_ordinary_account_is_refused(monkeypatch, capsys):
    monkeypatch.setattr(unlock.sys, "argv", ["nhub unlock"])
    monkeypatch.setattr("os.geteuid", lambda: 1000)

    assert unlock.main() == 1
    assert "sudo nhub unlock" in capsys.readouterr().err

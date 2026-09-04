"""The session secret: generated on the box, kept as state, never configuration."""

import stat

from neutrino_hub.web import auth


def test_a_missing_secret_is_generated_and_kept(tmp_path, monkeypatch):
    path = tmp_path / "state" / "session.secret"
    monkeypatch.setattr(auth, "WEB_SESSION_SECRET_PATH", path)

    generated = auth.session_secret()

    assert path.read_text().strip() == generated
    assert len(bytes.fromhex(generated)) == 32
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_an_existing_secret_is_read_back_unchanged(tmp_path, monkeypatch):
    path = tmp_path / "session.secret"
    path.write_text("ab" * 32 + "\n")
    monkeypatch.setattr(auth, "WEB_SESSION_SECRET_PATH", path)

    assert auth.session_secret() == "ab" * 32

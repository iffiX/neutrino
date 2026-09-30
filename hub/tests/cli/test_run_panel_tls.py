"""The panel's scheme at start: web/settings.json decides it.

Every start makes a missing authority and certificate, whichever scheme is
on. HTTPS serves the certificate; HTTPS with nothing to serve answers over
HTTP and says why, and the example ships with HTTPS off.
"""

import json

from neutrino_hub.cli import run
from neutrino_hub.exceptions import VaultLockedError
from neutrino_hub.utils.constants import UTILS_EXAMPLES_DIR


def served_with(monkeypatch, tmp_path, *, is_https: bool, has_key: bool, failure=None):
    calls: list = []

    def ensure() -> bool:
        calls.append("ensure")
        if failure is not None:
            raise failure
        return False

    key = tmp_path / "key.pem"
    if has_key:
        key.write_text("key")
    monkeypatch.setattr(run, "ensure_served", ensure)
    monkeypatch.setattr(run, "is_https_enabled", lambda: is_https)
    monkeypatch.setattr(run, "WEB_PANEL_TLS_SERVED_KEY_PATH", key)
    monkeypatch.setattr(run, "WEB_PANEL_TLS_SERVED_CERT_PATH", tmp_path / "cert.pem")
    return run._panel_certificate(), calls


def test_http_serves_no_certificate_and_still_makes_one(monkeypatch, tmp_path):
    arguments, calls = served_with(monkeypatch, tmp_path, is_https=False, has_key=True)

    assert arguments == {}
    assert calls == ["ensure"]


def test_https_serves_the_certificate(monkeypatch, tmp_path):
    arguments, _ = served_with(monkeypatch, tmp_path, is_https=True, has_key=True)

    assert arguments == {
        "ssl_certfile": str(tmp_path / "cert.pem"),
        "ssl_keyfile": str(tmp_path / "key.pem"),
    }


def test_https_with_nothing_to_serve_answers_over_http(monkeypatch, tmp_path, capsys):
    arguments, _ = served_with(
        monkeypatch,
        tmp_path,
        is_https=True,
        has_key=False,
        failure=VaultLockedError(),
    )

    assert arguments == {}
    error = capsys.readouterr().err
    assert '"code": "vault_locked"' in error
    assert '"code": "panel_tls_unavailable"' in error


def test_the_example_ships_with_https_off():
    example = json.loads(
        (UTILS_EXAMPLES_DIR / "web" / "settings.example.json").read_text(
            encoding="utf-8"
        )
    )

    assert example["is_https_enabled"] is False

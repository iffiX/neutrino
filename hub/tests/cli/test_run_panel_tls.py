"""The panel's certificate at start, which the HTTPS port serves.

Every start makes a missing authority and certificate. A certificate there to
serve is handed to the HTTPS port whatever the scheme setting says; with
nothing to serve the panel answers over HTTP alone and says why, and the
example ships with HTTPS off.
"""

import json

from neutrino_hub.cli import run
from neutrino_hub.exceptions import VaultLockedError
from neutrino_hub.utils.constants import UTILS_EXAMPLES_DIR
from neutrino_hub.web.constants import WEB_DEFAULT_HTTPS_LISTEN_PORT


def served_with(monkeypatch, tmp_path, *, has_key: bool, failure=None):
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
    monkeypatch.setattr(run, "WEB_PANEL_TLS_SERVED_KEY_PATH", key)
    monkeypatch.setattr(run, "WEB_PANEL_TLS_SERVED_CERT_PATH", tmp_path / "cert.pem")
    return run._panel_certificate(), calls


def test_a_certificate_there_is_served_and_still_made_first(monkeypatch, tmp_path):
    arguments, calls = served_with(monkeypatch, tmp_path, has_key=True)

    assert arguments == {
        "ssl_certfile": str(tmp_path / "cert.pem"),
        "ssl_keyfile": str(tmp_path / "key.pem"),
    }
    assert calls == ["ensure"]


def test_nothing_to_serve_leaves_the_https_port_out(monkeypatch, tmp_path, capsys):
    arguments, _ = served_with(
        monkeypatch,
        tmp_path,
        has_key=False,
        failure=VaultLockedError(),
    )

    assert arguments == {}
    error = capsys.readouterr().err
    assert '"code": "vault_locked"' in error
    assert '"code": "panel_tls_unavailable"' in error


def example() -> dict:
    return json.loads(
        (UTILS_EXAMPLES_DIR / "web" / "settings.example.json").read_text(
            encoding="utf-8"
        )
    )


def test_the_example_ships_with_https_off():
    assert example()["is_https_enabled"] is False


def test_the_example_carries_the_https_port():
    assert example()["https_listen_port"] == WEB_DEFAULT_HTTPS_LISTEN_PORT

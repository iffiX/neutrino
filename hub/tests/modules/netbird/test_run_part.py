"""How the hub's one service runs its own NetBird daemon outside Linux."""

from pathlib import Path

import pytest

from neutrino_hub.modules.netbird import run_part


@pytest.mark.parametrize(
    ("system", "address"),
    [
        ("darwin", "unix:///var/run/neutrino/hub/netbird.sock"),
        ("win32", "tcp://127.0.0.1:41732"),
    ],
)
def test_netbird_runs_on_the_hubs_own_address_and_log(monkeypatch, system, address):
    monkeypatch.setattr("sys.platform", system)
    monkeypatch.setattr(
        "neutrino_hub.utils.constants.UTILS_RUNTIME_ROOT", Path("/var/run/neutrino/hub")
    )
    monkeypatch.setattr(run_part, "NETBIRD_HUB_STATE_DIR", Path("/state/netbird"))
    monkeypatch.setattr(run_part, "UTILS_LOG_ROOT", Path("/log"))

    line = run_part.child_start_lines()["netbird"]

    assert line.argv[1:] == [
        "service",
        "run",
        "--config",
        str(Path("/state/netbird/config.json")),
        "--log-file",
        str(Path("/log/netbird.log")),
        "--daemon-addr",
        address,
    ]
    assert line.log_name == "netbird_console"


def test_the_service_makes_the_daemons_profile_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(run_part, "NETBIRD_HUB_STATE_DIR", tmp_path / "netbird")

    run_part.make_directories()

    assert (tmp_path / "netbird").is_dir()

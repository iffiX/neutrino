"""What every check here needs: a live box, and a session on its panel.

These tests reconfigure the machine they run on. Without a password they skip
rather than fail, so a `pytest` at the repository root walks past them instead
of trying to take the workstation's network apart.
"""

import os

import pytest

import machine_state
from panel_client import PanelClient

PANEL_DEFAULT_URL = "http://127.0.0.1:8080"
PANEL_PASSWORD_ENV = "NEUTRINO_PANEL_PASSWORD"
VAULT_PASSPHRASE_ENV = "NEUTRINO_VAULT_PASSPHRASE"


def pytest_addoption(parser) -> None:
    """Where the box is and how to get into it."""
    parser.addoption(
        "--panel",
        default=os.environ.get("NEUTRINO_PANEL_URL", PANEL_DEFAULT_URL),
        help="the panel to drive",
    )
    parser.addoption(
        "--password",
        default=os.environ.get(PANEL_PASSWORD_ENV, ""),
        help=f"its password; also read from ${PANEL_PASSWORD_ENV}",
    )
    parser.addoption(
        "--vault-passphrase",
        default=os.environ.get(VAULT_PASSPHRASE_ENV, ""),
        help=f"the box's vault passphrase; also read from ${VAULT_PASSPHRASE_ENV}",
    )
    parser.addoption(
        "--before",
        default=os.environ.get("NEUTRINO_BEFORE_STATE", ""),
        help="the machine's state as it was before the hub was installed",
    )
    parser.addoption(
        "--package",
        default=os.environ.get("NEUTRINO_PACKAGE", ""),
        help="the package file, for the checks that install it again",
    )
    parser.addoption(
        "--mode",
        default=os.environ.get("NEUTRINO_SETUP_MODE", ""),
        help="the mode the box was set up in: server, side_gateway or router",
    )


@pytest.fixture(scope="session")
def panel(request) -> PanelClient:
    """A session on the panel under test.

    Returns:
        A signed-in client.
    """
    password = request.config.getoption("--password")
    if not password:
        pytest.skip(
            f"these need a live box: pass --password or set ${PANEL_PASSWORD_ENV}"
        )
    client = PanelClient(base_url=request.config.getoption("--panel"))
    client.sign_in(password)
    return client


@pytest.fixture(scope="session")
def vault_passphrase(request) -> str:
    """The vault passphrase the box under test was set up with.

    Returns:
        The passphrase. Skips when none was named, so the restore checks walk
        past a box set up by other means.
    """
    passphrase = request.config.getoption("--vault-passphrase")
    if not passphrase:
        pytest.skip(
            "the restore checks need the box's vault passphrase: pass "
            f"--vault-passphrase or set ${VAULT_PASSPHRASE_ENV}"
        )
    return passphrase


@pytest.fixture(scope="session")
def before(request) -> dict:
    """This machine's network as it was before the hub was installed.

    Returns:
        The recorded snapshot.
    """
    path = request.config.getoption("--before")
    if not path:
        pytest.skip("no snapshot of the machine from before the install")
    return machine_state.read_snapshot(path)


@pytest.fixture(scope="session")
def package(request) -> str:
    """The package file under test.

    Returns:
        Its path. Skips when none was named, so a run against a box that was
        set up by other means walks past the reinstall checks.
    """
    path = request.config.getoption("--package")
    if not path:
        pytest.skip("no package to install again: pass --package")
    return path


@pytest.fixture(scope="session")
def mode(request) -> str:
    """The mode the box under test was set up in."""
    chosen = request.config.getoption("--mode")
    if not chosen:
        pytest.skip("the box's mode was not named")
    return chosen

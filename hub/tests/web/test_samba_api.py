"""The Samba tab's API, with the system underneath replaced.

The account survey and the password setter are stubbed; what is exercised is
the request path — validation, the config round-trip, and the one rule with
teeth: removing a user scrubs it from every share that named it.
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from neutrino_hub.modules.samba.config import SambaConfig
from neutrino_hub.modules.samba.ops import SambaUserState
from neutrino_hub.web.dependencies import get_runtime, require_session
from neutrino_hub.web.routers import samba as samba_router


class FakeUserManager:
    """Accounts exist and have passwords; setting one is recorded."""

    def __init__(self):
        self.password_set_for: list[str] = []

    def survey(self, users):
        return [
            SambaUserState(name=name, is_present=True, has_password=True)
            for name in users
        ]

    def set_password(self, name, password):
        self.password_set_for.append(name)


class FakeRuntime:
    """Just the parts of PanelRuntime the Samba routes reach for."""

    def __init__(self, config: SambaConfig):
        self._config = config
        self.applied_count = 0

    def samba(self) -> SambaConfig:
        return SambaConfig.from_dict(self._config.to_dict())

    def write_samba(self, config: SambaConfig) -> None:
        config.validate()
        self._config = config

    async def apply_samba(self) -> str:
        self.applied_count += 1
        return "reloaded smbd"


@pytest.fixture
def box(monkeypatch):
    config = SambaConfig.from_dict(
        {
            "shares": [
                {"name": "share", "path": "/srv/share", "valid_users": []},
                {"name": "mine", "path": "/srv/mine", "valid_users": ["ann"]},
            ],
            "users": ["ann", "bob"],
        }
    )
    runtime = FakeRuntime(config)
    manager = FakeUserManager()
    monkeypatch.setattr(samba_router, "SambaUserManager", lambda: manager)

    app = FastAPI()
    app.include_router(samba_router.router)
    app.dependency_overrides[require_session] = lambda: None
    app.dependency_overrides[get_runtime] = lambda: runtime
    with TestClient(app) as client:
        yield client, runtime, manager


def test_the_view_reports_shares_and_surveyed_users(box):
    client, _, _ = box

    payload = client.get("/api/samba").json()

    assert [share["name"] for share in payload["shares"]] == ["share", "mine"]
    assert [user["name"] for user in payload["users"]] == ["ann", "bob"]
    assert payload["users"][0]["has_password"] is True


def test_saving_shares_replaces_the_list(box):
    client, runtime, _ = box

    response = client.put(
        "/api/samba/shares",
        json={"shares": [{"name": "media", "path": "/srv/media"}]},
    )

    assert response.status_code == 200
    assert [share.name for share in runtime.samba().shares] == ["media"]


def test_a_bad_share_is_refused_and_nothing_is_stored(box):
    client, runtime, _ = box

    response = client.put(
        "/api/samba/shares",
        json={"shares": [{"name": "global", "path": "/srv/x"}]},
    )

    assert response.status_code == 400
    assert [share.name for share in runtime.samba().shares] == ["share", "mine"]


def test_removing_a_user_scrubs_it_from_the_shares_that_named_it(box):
    """A share restricted to accounts that no longer exist would refuse
    everyone, and nothing would say why."""
    client, runtime, _ = box

    response = client.put("/api/samba/users", json={"users": ["bob"]})

    assert response.status_code == 200
    config = runtime.samba()
    assert config.users == ["bob"]
    restricted = next(share for share in config.shares if share.name == "mine")
    assert restricted.valid_users == []


def test_a_password_lands_only_on_a_configured_user(box):
    client, _, manager = box

    good = client.post("/api/samba/users/ann/password", json={"password": "s3cret"})
    bad = client.post("/api/samba/users/ghost/password", json={"password": "x"})

    assert good.status_code == 200
    assert bad.status_code == 404
    assert manager.password_set_for == ["ann"]


def test_apply_reports_what_it_did(box):
    client, runtime, _ = box

    payload = client.post("/api/samba/apply").json()

    assert payload["is_applied"] is True
    assert runtime.applied_count == 1

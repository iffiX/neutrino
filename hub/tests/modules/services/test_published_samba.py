"""The file share's shares as the published list reads them from a device."""

from neutrino_hub.modules.services.published import PublishedServiceCache

DEVICE = "d1d1d1d1d1d1d1d1"
PLATFORM = {"os": "windows", "arch": "amd64"}


class FakeDesiredStates:
    """The file share's file and enabled accounts of one device."""

    def __init__(self, *, enabled: list, stored: dict):
        self._enabled = enabled
        self._stored = stored

    def want_of(self, key: str, module: str) -> str:
        return "running"

    def enabled_accounts(self, key: str, module: str) -> list:
        return list(self._enabled)

    def read(self, key: str, module: str) -> dict:
        return dict(self._stored)


def hosted(enabled: list, stored: dict) -> dict:
    cache = PublishedServiceCache(
        declared_probe=None,
        served_models=None,
        units=None,
        desired_states=FakeDesiredStates(enabled=enabled, stored=stored),
    )
    status = {"state": "running", "details": {"is_active": True}}
    return cache._hosted(DEVICE, "samba", status, PLATFORM)


def test_a_folder_share_lists_its_enabled_accounts_each_with_its_smb_user():
    """An account the file share no longer enables gives the share no entry,
    and a share with no account is listed with none."""
    stored = {
        "shares": [
            {"name": "lab", "path": "C:\\Lab", "accounts": ["ann", "gone"]},
            {"name": "empty", "path": "C:\\Empty", "accounts": []},
        ]
    }

    samba = hosted(["ann", "averyveryverylongaccountname"], stored)

    assert samba["shares"] == [
        {"name": "ann", "user": "neutrino-ann"},
        {"name": "averyveryverylongaccountname", "user": "neutrino-averyveryve"},
    ]
    assert samba["folder_shares"] == [
        {"name": "lab", "accounts": [{"account": "ann", "user": "neutrino-ann"}]},
        {"name": "empty", "accounts": []},
    ]

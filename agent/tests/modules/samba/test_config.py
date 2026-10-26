"""The share configuration and the checks that keep it servable.

What these pin beside the shapes: the passwords map reads and round-trips;
share names are the machine's account names, dots and up to 80 characters
allowed; a user name is the module's ``neutrino-`` account, a space allowed
on Windows and macOS; a share's forced user is a unix name; two users
of one name are ``user_name_duplicate`` on Linux and ``user_name_taken`` on
Windows and macOS.
"""

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.samba.config import SambaConfig


def config_with(**overrides) -> SambaConfig:
    data = {
        "shares": [{"name": "share", "path": "/srv/share", "valid_users": []}],
        "users": ["ann"],
        "allowed_subnets": ["192.168.100.0/24"],
    }
    data.update(overrides)
    return SambaConfig.from_dict(data)


def test_a_sound_configuration_passes():
    config_with().validate()


def test_the_parse_survives_a_round_trip():
    config = config_with()

    assert SambaConfig.from_dict(config.to_dict()).to_dict() == config.to_dict()
    assert config.allowed_subnets == ["192.168.100.0/24"]


@pytest.mark.parametrize(
    "name, code",
    [
        ("", "share_name_invalid"),
        ("global", "share_name_reserved"),
        ("Printers", "share_name_reserved"),
        ("a\nb", "share_name_invalid"),
        ("x" * 81, "share_name_invalid"),
        ("[injected]", "share_name_invalid"),
    ],
)
def test_a_share_name_that_could_bite_is_refused_typed(name, code):
    config = config_with(shares=[{"name": name, "path": "/srv/x"}])

    with pytest.raises(ModuleApplyError) as refused:
        config.validate()

    assert refused.value.code == code


def test_two_shares_cannot_share_a_name_even_by_case():
    config = config_with(
        shares=[
            {"name": "media", "path": "/srv/a"},
            {"name": "Media", "path": "/srv/b"},
        ]
    )

    with pytest.raises(ModuleApplyError) as refused:
        config.validate()

    assert refused.value.code == "share_name_duplicate"


def test_a_relative_share_path_is_refused():
    config = config_with(shares=[{"name": "share", "path": "srv/share"}])

    with pytest.raises(ModuleApplyError) as refused:
        config.validate()

    assert refused.value.code == "share_path_relative"


@pytest.mark.parametrize("name", ["-dash", "a b", "root\n", "x" * 33, "a:b"])
def test_a_user_name_that_is_not_a_unix_name_is_refused(name):
    with pytest.raises(ModuleApplyError) as refused:
        config_with(users=[name]).validate()

    assert refused.value.code == "user_name_invalid"


def test_the_forced_users_are_the_shares_accounts_once_each():
    config = config_with(
        shares=[
            {"name": "ann", "path": "/home/ann", "force_user": "ann"},
            {"name": "pool", "path": "/pool"},
            {"name": "ann2", "path": "/srv/ann", "force_user": "ann"},
        ]
    )

    assert config.forced_users() == ["ann"]
    assert SambaConfig.from_dict(config.to_dict()).shares[0].force_user == "ann"


def test_a_forced_user_that_is_not_a_unix_name_is_refused():
    config = config_with(
        shares=[{"name": "share", "path": "/srv/share", "force_user": "a b"}]
    )

    with pytest.raises(ModuleApplyError) as refused:
        config.validate()

    assert (refused.value.code, refused.value.params) == (
        "user_name_invalid",
        {"user": "a b"},
    )


def test_a_share_cannot_admit_a_user_that_does_not_exist():
    config = config_with(
        shares=[{"name": "share", "path": "/srv/share", "valid_users": ["ghost"]}]
    )

    with pytest.raises(ModuleApplyError) as refused:
        config.validate()

    assert refused.value.code == "share_user_unknown"
    assert refused.value.params == {"name": "share", "user": "ghost"}


@pytest.mark.parametrize("path", ["D:\\media", "c:\\Users\\Public\\share"])
def test_a_windows_share_is_absolute_from_a_drive(path):
    config_with(shares=[{"name": "share", "path": path}]).validate(os_name="windows")


@pytest.mark.parametrize("path", ["/srv/share", "media", "\\\\host\\share", "D:media"])
def test_a_windows_share_path_without_a_drive_is_refused(path):
    config = config_with(shares=[{"name": "share", "path": path}])

    with pytest.raises(ModuleApplyError) as refused:
        config.validate(os_name="windows")

    assert refused.value.code == "share_path_relative"


def test_a_windows_account_name_is_at_most_twenty_characters():
    shares = [{"name": "share", "path": "D:\\share"}]
    config_with(shares=shares, users=["a" * 20]).validate(os_name="windows")
    config_with(users=["a" * 21]).validate(os_name="darwin")

    with pytest.raises(ModuleApplyError) as refused:
        config_with(shares=shares, users=["a" * 21]).validate(os_name="windows")

    assert refused.value.code == "user_name_invalid"


def test_the_passwords_read_and_round_trip():
    config = config_with(passwords={"ann": "generated"})

    assert config.passwords == {"ann": "generated"}
    assert SambaConfig.from_dict(config.to_dict()).passwords == {"ann": "generated"}
    assert config_with(passwords="nothing").passwords == {}


def test_an_account_with_a_dot_is_a_share_and_a_user():
    config_with(
        shares=[{"name": "first.last", "path": "/home/first.last"}],
        users=["first.last"],
    ).validate()


def test_a_native_account_may_hold_a_space():
    shares = [{"name": "John Smith", "path": "C:\\Users\\John Smith"}]

    config_with(shares=shares, users=["neutrino-John Smith"]).validate(
        os_name="windows"
    )


@pytest.mark.parametrize(
    "os_name, code",
    [("linux", "user_name_duplicate"), ("windows", "user_name_taken")],
)
def test_two_users_of_one_name_are_refused(os_name, code):
    shares = [{"name": "share", "path": "D:\\s" if os_name == "windows" else "/s"}]
    users = ["smb_ann", "smb_ann"]

    with pytest.raises(ModuleApplyError) as refused:
        config_with(shares=shares, users=users).validate(os_name=os_name)

    assert (refused.value.code, refused.value.params) == (code, {"user": "smb_ann"})

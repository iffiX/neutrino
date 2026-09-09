"""The share configuration and the checks that keep it servable."""

import pytest

from neutrino_agent.modules.base import ModuleApplyError
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
        ("x" * 33, "share_name_invalid"),
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


@pytest.mark.parametrize("name", ["Ann", "0start", "a b", "root\n", "x" * 33])
def test_a_user_name_that_is_not_a_unix_name_is_refused(name):
    with pytest.raises(ModuleApplyError) as refused:
        config_with(users=[name]).validate()

    assert refused.value.code == "user_name_invalid"


def test_a_share_cannot_admit_a_user_that_does_not_exist():
    config = config_with(
        shares=[{"name": "share", "path": "/srv/share", "valid_users": ["ghost"]}]
    )

    with pytest.raises(ModuleApplyError) as refused:
        config.validate()

    assert refused.value.code == "share_user_unknown"
    assert refused.value.params == {"name": "share", "user": "ghost"}

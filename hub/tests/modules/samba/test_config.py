"""The share configuration and the checks that keep it servable.

Names here end up as smb.conf section headers and as unix accounts, so the
validation is less about tidiness than about what a crafted name could become
in either place.
"""

import pytest

from neutrino_hub.modules.samba.config import SambaConfig


def config_with(**overrides) -> SambaConfig:
    data = {
        "shares": [
            {"name": "share", "path": "/srv/share", "valid_users": []},
        ],
        "users": ["ann"],
    }
    data.update(overrides)
    return SambaConfig.from_dict(data)


def test_a_sound_configuration_passes():
    config_with().validate()


def test_the_parse_survives_a_round_trip():
    config = config_with()

    assert SambaConfig.from_dict(config.to_dict()).to_dict() == config.to_dict()


@pytest.mark.parametrize(
    "name",
    [
        "",
        "global",
        "Printers",
        "a\nb",
        "x" * 33,
        "[injected]",
    ],
)
def test_a_share_name_that_could_bite_is_refused(name):
    config = config_with(shares=[{"name": name, "path": "/srv/x"}])

    with pytest.raises(ValueError):
        config.validate()


def test_two_shares_cannot_share_a_name_even_by_case():
    """Share names are case-insensitive on the wire, so Share and share are
    one name to a client and must be one name here."""
    config = config_with(
        shares=[
            {"name": "media", "path": "/srv/a"},
            {"name": "Media", "path": "/srv/b"},
        ]
    )

    with pytest.raises(ValueError):
        config.validate()


def test_a_relative_share_path_is_refused():
    config = config_with(shares=[{"name": "share", "path": "srv/share"}])

    with pytest.raises(ValueError):
        config.validate()


@pytest.mark.parametrize("name", ["Ann", "0start", "a b", "root\n", "x" * 33])
def test_a_user_name_that_is_not_a_unix_name_is_refused(name):
    config = config_with(users=[name])

    with pytest.raises(ValueError):
        config.validate()


def test_a_share_cannot_admit_a_user_that_does_not_exist():
    """The failure this prevents is silent: Samba would accept the config and
    then refuse everyone the share names."""
    config = config_with(
        shares=[{"name": "share", "path": "/srv/share", "valid_users": ["ghost"]}]
    )

    with pytest.raises(ValueError):
        config.validate()

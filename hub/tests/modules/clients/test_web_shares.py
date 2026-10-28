"""The Web shares as stored: the record, its secrets, its link and its state.

What these pin, by protocol.md's "Web shares" and transport.md's "The
links": a share keeps the SHA-256 of its ticket alone, its ufrag in the
clear and its pwd sealed, and a guest account's password and secret sealed;
the ticket is 18 random bytes, the ufrag 24 hex characters and the pwd 32;
the link is ``<site>/__neutrino/#`` and base64url JSON with no padding; an
expired share is not live; the guest accounts of an app open for its state
and stay closed while the vault is locked; and a share's state follows its
entry, its machine and its guest.
"""

import base64
import hashlib
import json
import re

import pytest

from neutrino_hub.exceptions import VaultLockedError
from neutrino_hub.modules.clients import web_shares
from neutrino_hub.modules.clients.web_shares import (
    WebShareRegistry,
    guest_accounts,
    live_pairs,
    make_share,
    share_link,
    share_state,
    taken_guest_accounts,
)
from tests.conftest import unlock_vault

NOW = 1_800_000_000


@pytest.fixture
def config(monkeypatch, tmp_path):
    monkeypatch.setattr("neutrino_hub.utils.json_file.UTILS_CONFIG_DIR", tmp_path)
    unlock_vault(monkeypatch, tmp_path)
    return tmp_path


def made(**fields):
    defaults = {
        "name": "paper",
        "app_id": "ayakaleaf_dev1",
        "app_title": "Ayakaleaf",
        "entry_id": "ayakaleaf_dev1_web",
        "device_id": "dev1",
        "module": "ayakaleaf",
        "days": 7,
        "taken_accounts": set(),
        "is_guest": False,
        "now": NOW,
    }
    defaults.update(fields)
    return make_share(**defaults)


def decoded(link: str) -> dict:
    fragment = link.split("#", 1)[1]
    assert "=" not in fragment
    return json.loads(base64.urlsafe_b64decode(fragment + "=" * (-len(fragment) % 4)))


def test_a_share_keeps_its_ticket_hash_its_ufrag_and_its_pwd_sealed(config):
    share, secrets = made()

    assert len(secrets.ticket) == 24
    assert share.ticket_sha256 == hashlib.sha256(secrets.ticket.encode()).hexdigest()
    assert re.fullmatch(r"[0-9a-f]{24}", share.ufrag)
    assert re.fullmatch(r"[0-9a-f]{32}", secrets.pwd)
    assert secrets.pwd not in json.dumps(share.to_dict())
    assert share.pwd() == secrets.pwd
    assert share.is_ticket(secrets.ticket) and not share.is_ticket("other")
    assert share.expires_at == NOW + 7 * 86400 and share.guest is None


def test_a_share_until_revoked_has_no_expiry(config):
    share, _ = made(days=None)

    assert share.expires_at is None and not share.is_expired(NOW + 10**9)


def test_a_guest_account_is_made_sealed_and_unlike_the_taken_ones(config, monkeypatch):
    picks = iter("abcdabcdwxyz")
    monkeypatch.setattr(web_shares.secrets, "choice", lambda alphabet: next(picks))

    share, _ = made(is_guest=True, taken_accounts={"guest-abcd"})

    assert share.guest.account == "guest-wxyz"
    assert share.guest.email == "guest-wxyz@share.neutrino"
    opened = share.guest.opened()
    assert set(opened) == {"account", "email", "password", "secret"}
    stored = json.dumps(share.to_dict())
    assert opened["password"] not in stored and opened["secret"] not in stored


def test_the_registry_stores_the_record_shape(config):
    share, _ = made(is_guest=True)
    WebShareRegistry().add(share)

    stored = json.loads((config / "clients" / "web_shares.json").read_text())

    record = stored["shares"][0]
    assert set(record) == {
        "id",
        "name",
        "app_id",
        "app_title",
        "entry_id",
        "device_id",
        "module",
        "created_at",
        "expires_at",
        "ticket_sha256",
        "ufrag",
        "pwd_sealed",
        "guest",
    }
    assert set(record["guest"]) == {
        "account",
        "email",
        "password_sealed",
        "secret_sealed",
    }
    assert WebShareRegistry().get(share.id) == share
    assert WebShareRegistry().find_by_ufrag(share.ufrag) == share
    assert taken_guest_accounts("dev1") == {share.guest.account}
    assert WebShareRegistry().remove_where(lambda s: s.id == share.id) == [share]
    assert WebShareRegistry().all() == []


def test_the_link_holds_the_hub_the_pair_the_ticket_and_the_app(config):
    share, secrets = made()

    link = share_link(
        "https://share.example/",
        ip="203.0.113.7",
        port=8443,
        fingerprint="AB:CD",
        share=share,
        share_secrets=secrets,
        title="Ayakaleaf",
        path="/project",
    )

    assert link.startswith("https://share.example/__neutrino/#")
    assert decoded(link) == {
        "v": 1,
        "hub": {"ip": "203.0.113.7", "port": 8443, "fp": "AB:CD"},
        "ice": {"ufrag": share.ufrag, "pwd": secrets.pwd},
        "ticket": secrets.ticket,
        "app": {"entry": share.entry_id, "title": "Ayakaleaf", "path": "/project"},
    }
    plain = share_link(
        "https://share.example",
        ip="192.0.2.1",
        port=8443,
        fingerprint="AB",
        share=share,
        share_secrets=secrets,
        title="Gitea",
    )
    assert "path" not in decoded(plain)["app"]


def test_an_expired_share_has_no_live_pair(config):
    live, _ = made(now=NOW)
    gone, _ = made(days=1, now=NOW - 2 * 86400)
    WebShareRegistry().add(live)
    WebShareRegistry().add(gone)

    pairs = live_pairs(now=NOW)

    assert [pair["ufrag"] for pair in pairs] == [live.ufrag]


def test_a_locked_vault_leaves_the_pairs_and_the_guests_empty(config, monkeypatch):
    share, _ = made(is_guest=True, now=None)
    WebShareRegistry().add(share)

    def locked(sealed, aad):
        raise VaultLockedError()

    monkeypatch.setattr(web_shares, "unseal_bytes", locked)

    assert live_pairs() == []
    assert guest_accounts("dev1", "ayakaleaf_dev1") == []


def test_the_guest_accounts_of_an_app_open_for_its_state(config):
    first, _ = made(is_guest=True, now=None)
    other_app, _ = made(is_guest=True, now=None, app_id="ayakaleaf_dev2")
    no_guest, _ = made(now=None)
    for share in (first, other_app, no_guest):
        WebShareRegistry().add(share)

    guests = guest_accounts("dev1", "ayakaleaf_dev1")

    assert [guest["account"] for guest in guests] == [first.guest.account]
    assert guests[0]["secret"] and guests[0]["password"]


@pytest.mark.parametrize(
    "is_published, is_online, reported, is_guest, expected",
    [
        (True, False, [], False, ("unavailable", "", {})),
        (False, True, [], False, ("unavailable", "", {})),
        (True, True, [], False, ("active", "", {})),
        (True, True, [], True, ("preparing", "", {})),
        (
            True,
            True,
            [
                {
                    "account": "ACCOUNT",
                    "code": "ayakaleaf_guest_failed",
                    "params": {"step": "register", "detail": "500"},
                }
            ],
            True,
            (
                "failed",
                "ayakaleaf_guest_failed",
                {"step": "register", "detail": "500"},
            ),
        ),
        (
            True,
            True,
            [{"account": "ACCOUNT", "code": "", "params": {}}],
            True,
            ("active", "", {}),
        ),
    ],
)
def test_a_shares_state_follows_its_entry_its_machine_and_its_guest(
    config, is_published, is_online, reported, is_guest, expected
):
    share, _ = made(is_guest=is_guest)
    guests = [
        {**item, "account": share.guest.account if share.guest else ""}
        for item in reported
    ]

    state = share_state(
        share, is_published=is_published, is_online=is_online, guests_reported=guests
    )

    assert state == expected

"""The shared password rules: both rule sets and the entropy estimate."""

import pytest

from neutrino_hub.utils.passwords import (
    PASSWORDS_ERROR_MISSING_CLASSES,
    PASSWORDS_ERROR_TOO_SHORT,
    PASSWORDS_MASTER_RULES,
    PASSWORDS_PANEL_RULES,
    PasswordRuleError,
    entropy_bits,
    validate,
)


def test_the_panel_rules_take_length_alone():
    validate("eightchr", PASSWORDS_PANEL_RULES)


def test_the_panel_rules_refuse_a_short_password():
    with pytest.raises(PasswordRuleError) as refusal:
        validate("seven77", PASSWORDS_PANEL_RULES)
    assert refusal.value.code == PASSWORDS_ERROR_TOO_SHORT
    assert refusal.value.params == {"min_length": PASSWORDS_PANEL_RULES.min_length}


def test_the_master_rules_need_sixteen_and_every_class():
    validate("A-vault-passphrase-16!", PASSWORDS_MASTER_RULES)  # scan: allow


def test_the_master_rules_refuse_a_short_passphrase_by_length_first():
    with pytest.raises(PasswordRuleError) as refusal:
        validate("Aa1!aa", PASSWORDS_MASTER_RULES)
    assert refusal.value.code == PASSWORDS_ERROR_TOO_SHORT


@pytest.mark.parametrize(
    ("candidate", "missing"),
    [
        ("all-lowercase-and-long", ["uppercase", "digit"]),
        ("NOUPPERCASEHERE1234!", ["lowercase"]),
        ("No-symbols-here-1234x".replace("-", "x"), ["symbol"]),
        ("No.Digits.Here.At.All", ["digit"]),
    ],
)
def test_the_master_rules_name_every_missing_class(candidate, missing):
    with pytest.raises(PasswordRuleError) as refusal:
        validate(candidate, PASSWORDS_MASTER_RULES)
    assert refusal.value.code == PASSWORDS_ERROR_MISSING_CLASSES
    assert refusal.value.params["classes"] == missing


def test_entropy_grows_with_length_and_pool():
    assert entropy_bits("") == 0.0
    assert entropy_bits("aaaa") < entropy_bits("aaaaaaaa")
    assert entropy_bits("aaaaaaaa") < entropy_bits("aaaaAAA1")
    assert entropy_bits("aaaaAAA1") < entropy_bits("aaaaAA1!")


def test_entropy_counts_the_combined_pool():
    # Eight lowercase characters: 8 * log2(26).
    assert entropy_bits("abcdefgh") == pytest.approx(8 * 4.700439718)

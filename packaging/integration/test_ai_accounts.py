"""Subscription accounts against a live box.

What no unit test can promise: that the installed panel reaches the gateway's
management API with the key an apply rendered, and that the flows it offers
are the ones this build of the binary actually carries. Read-only except the
logins it starts, which it cancels again; nothing here can finish a sign-in,
because that needs somebody's subscription.
"""

import pytest

LOGIN_ERROR_CODES = {"gateway_unreachable", "management_key_missing"}


def accounts_or_skip(panel):
    """The accounts payload, skipping where the gateway is not answering.

    Args:
        panel: The live panel session.

    Returns:
        The decoded accounts view.
    """
    status, body = panel.call("GET", "/cliproxyapi/accounts")
    if status == 502:
        pytest.skip(f"gateway not answering: {body['detail']['code']}")
    assert status == 200, body
    return body


def test_accounts_answer_the_contract_shape(panel):
    body = accounts_or_skip(panel)
    assert isinstance(body["accounts"], list)
    assert "anthropic" in body["login_kinds"]
    assert "codex" in body["login_kinds"]
    for account in body["accounts"]:
        assert account["name"]
        assert account["provider"]
        assert isinstance(account["is_disabled"], bool)
        assert isinstance(account["is_unavailable"], bool)
        assert "path" not in account
        assert "access_token" not in account


def test_the_status_counts_the_accounts(panel):
    body = accounts_or_skip(panel)
    status, view = panel.call("GET", "/cliproxyapi")
    assert status == 200, view
    assert view["account_count"] == len(body["accounts"])


def test_a_login_hands_back_a_url_and_stays_pending(panel):
    accounts_or_skip(panel)
    status, login = panel.call(
        "POST", "/cliproxyapi/account_logins", {"kind": "anthropic"}
    )
    assert status == 200, login
    assert login["state"]
    assert login["url"].startswith("https://")
    assert login["flow"] == "redirect"
    try:
        status, state = panel.call(
            "GET", f"/cliproxyapi/account_logins/{login['state']}"
        )
        assert status == 200, state
        assert state["status"] == "pending"
    finally:
        panel.call("DELETE", f"/cliproxyapi/account_logins/{login['state']}")


def test_a_device_login_hands_back_a_code_to_type(panel):
    accounts_or_skip(panel)
    status, login = panel.call("POST", "/cliproxyapi/account_logins", {"kind": "kimi"})
    assert status == 200, login
    assert login["flow"] == "device"
    assert login["user_code"]
    panel.call("DELETE", f"/cliproxyapi/account_logins/{login['state']}")


def test_refusals_are_coded(panel):
    accounts_or_skip(panel)
    status, body = panel.call(
        "POST", "/cliproxyapi/account_logins", {"kind": "gemini"}
    )
    assert status == 422
    assert body["detail"] == {
        "code": "unsupported_kind",
        "params": {"kind": "gemini"},
    }

    status, body = panel.call(
        "PUT", "/cliproxyapi/account_logins/no-such-state/code", {"code": "x"}
    )
    assert status == 404
    assert body["detail"]["code"] == "login_expired"

    status, body = panel.call("DELETE", "/cliproxyapi/accounts/no-such-account.json")
    assert status == 404
    assert body["detail"]["code"] == "unknown_account"


def test_signing_in_is_not_a_configuration_change(panel):
    """Accounts are state: starting one never asks the page to apply."""
    accounts_or_skip(panel)
    status, before = panel.call("GET", "/cliproxyapi")
    assert status == 200, before
    status, login = panel.call(
        "POST", "/cliproxyapi/account_logins", {"kind": "anthropic"}
    )
    assert status == 200, login
    try:
        status, after = panel.call("GET", "/cliproxyapi")
        assert status == 200, after
        assert after["is_serving_stale"] == before["is_serving_stale"]
    finally:
        panel.call("DELETE", f"/cliproxyapi/account_logins/{login['state']}")

"""What the secret scanner must catch, and what it must stay quiet about.

The quiet half matters as much as the loud half. A scanner that cries at every
constant gets silenced, and a silenced scanner is worse than none — so the
cases below pin both directions, and several lines here carry `scan: allow`
because they hold, on purpose, exactly what the scanner is built to find.
"""

from neutrino_hub.utils.secret_scan import (
    SecretScanner,
    is_scannable,
    is_catalog_line,
    is_worth_reporting,
    shannon_entropy,
)

# A string with no pattern in it, which is the whole point of the entropy
# rule and the reason this line says it was looked at.
RANDOM_STRING = "aZ3kQ9mX7pL2wR8tY5uH1nB4vC6dF0gJ"  # scan: allow

# A base64 value long enough to be a real credential, which is what makes
# it the case that must get through.
UNFAMILIAR_LINE = 'secret = "Zm9vYmFyYmF6cXV4MTIzNDU2Nzg5MA=="'  # scan: allow


def rules(text: str) -> list:
    """Every rule that fires on a snippet, as a list of slugs."""
    return [finding.rule for finding in SecretScanner().scan_text(text, path="x")]


def test_a_real_hardware_mac_is_reported():
    assert "hardware-mac" in rules("arp says 0c:5b:8f:11:33:57 here")  # scan: allow


def test_a_documentation_mac_is_not():
    # The locally-administered bit is what documentation addresses set, so
    # every conventional fake is quiet without being on any list.
    assert rules("aa:bb:cc:dd:ee:ff") == []
    assert rules("02:00:5e:76:21:30") == []
    assert rules("00:00:00:00:00:00") == []


def test_evenly_spaced_bytes_read_as_somebody_counting():
    assert rules("11:22:33:44:55:66") == []


def test_a_public_address_is_reported():
    assert "public-address" in rules("gateway=93.184.216.34")  # scan: allow


def test_private_documentation_and_resolver_addresses_are_not():
    for address in (
        "192.168.100.1",
        "10.0.0.1",
        "172.16.4.4",
        "127.0.0.1",
        "203.0.113.10",
        "198.51.100.129",
        "100.88.0.1",
        "1.1.1.1",
        "223.5.5.5",
        "240.0.0.0",
    ):
        assert rules(address) == [], address


def test_a_version_string_is_not_an_address():
    assert rules("Chrome/126.0.0.0 Safari/537.36") == []


def test_a_leading_zero_means_it_is_not_an_address():
    assert rules("`010.1.1.1` cannot be read two ways") == []


def test_vendor_tokens_are_reported():
    assert "vendor-token" in rules('key = "ghp_' + "a" * 30 + '"')  # scan: allow
    assert "vendor-token" in rules("AKIAQQQQWWWWEEEERRRR")  # scan: allow


def test_a_password_hash_is_reported():
    assert "password-hash" in rules("$argon2id$v=19$m=65536,t=3$abcdef")  # scan: allow


def test_a_proxy_share_link_is_reported():
    assert "proxy-share-link" in rules("vless://uuid@host:443?x=1")  # scan: allow


def test_credentials_inside_a_url_are_reported():
    assert "url-credentials" in rules("https://joe:hunter2@host/x")  # scan: allow


def test_a_private_key_needs_a_body_to_count():
    mention = "must begin with '-----BEGIN OPENSSH PRIVATE KEY-----' or similar"
    assert rules(mention) == []

    real = "-----BEGIN OPENSSH PRIVATE KEY-----\n" + "b3BlbnNzaC1rZXktdjEAAAAA" * 3
    assert "private-key" in rules(real)


def test_an_assigned_placeholder_is_not_a_credential():
    assert rules('"api_key": "sk-ant-replace-me"') == []
    assert rules('password = "PLACEHOLDER_PASSWORD"') == []


def test_an_assigned_identifier_is_not_a_credential():
    assert rules("setup_key=DEFAULT_SETUP_KEY") == []


def test_shouted_constants_are_not_high_entropy():
    assert rules("architectures=SAMBA_SUPPORTED_ARCHITECTURES,") == []
    assert rules("CapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_BIND_SERVICE") == []
    assert rules("Environment=GITEA_WORK_DIR=/var/lib/gitea") == []  # scan: allow


def test_a_random_string_is_high_entropy():
    assert "high-entropy" in rules("token=" + RANDOM_STRING)


def test_entropy_can_be_switched_off():
    scanner = SecretScanner(is_entropy_checked=False)
    noisy = RANDOM_STRING
    assert scanner.scan_text(noisy, path="x") == []


def test_a_line_marked_as_looked_at_is_left_alone():
    assert rules("mac 0c:5b:8f:11:33:57  # scan: allow") == []


def test_generated_lines_are_too_long_to_judge():
    assert rules("x" * 2001 + " 0c:5b:8f:11:33:57") == []  # scan: allow


def test_build_output_and_binaries_are_not_read():
    assert is_scannable("modules/xray/renderer.py") is True
    assert is_scannable("web/frontend/node_modules/x/index.js") is False
    assert is_scannable("hub/frontend/dist/assets/main.js") is False
    assert is_scannable("hub/frontend/package-lock.json") is False
    assert is_scannable("resources/icon.svg") is False


def test_entropy_separates_prose_from_randomness():
    assert shannon_entropy("") == 0.0
    assert shannon_entropy("aaaaaaaa") == 0.0
    assert shannon_entropy("the quick brown fox") < 4.4
    assert shannon_entropy(RANDOM_STRING) > 4.4


def test_findings_do_not_republish_what_they_found():
    secret = "ghp_" + "abcdefghij" * 3
    finding = SecretScanner().scan_text(f'k = "{secret}"', path="x")[0]
    assert secret not in finding.detail
    assert finding.line_number == 1


def test_a_four_part_version_number_is_not_an_address():
    assert rules('"version": "4.8.6.2"') == []
    assert rules("fakedesk release 4.8.5.1 for arm64") == []
    assert rules("v1.2.3.4") == []


def test_a_real_address_beside_a_version_is_still_reported():
    assert "public-address" in rules(
        'version "4.8.6.2" reached 93.184.216.34'  # scan: allow
    )


def test_small_parts_all_the_way_down_read_as_a_version():
    assert rules("installing 4.8.6.2 on the device") == []
    assert rules('"fakedesk": "4.8.6.2"') == []
    assert rules("bumped to 10.15.3.1") == []


def test_an_address_with_a_large_part_is_still_an_address():
    assert "public-address" in rules("reached 93.184.216.34")  # scan: allow
    assert "public-address" in rules("reached 176.122.179.135")  # scan: allow


def test_another_tools_finding_on_a_placeholder_is_not_news():
    assert is_worth_reporting('"api_key": "sk-ant-replace-me"') is False
    assert is_worth_reporting('token = "PLACEHOLDER_TOKEN_VALUE"') is False


def test_another_tools_finding_on_a_short_fixture_is_not_news():
    assert is_worth_reporting('api_key="sk-x",') is False
    assert is_worth_reporting('"LFS_JWT_SECRET": "lf",') is False


def test_another_tools_finding_on_a_marked_line_is_not_news():
    assert is_worth_reporting('key = "realvaluehere"  # scan: allow') is False


def test_a_mentioned_private_key_is_not_news_but_a_pasted_one_is():
    mention = "should begin with '-----BEGIN OPENSSH PRIVATE KEY-----'"
    assert is_worth_reporting(mention, following="paste it below") is False
    assert (
        is_worth_reporting(
            "-----BEGIN OPENSSH PRIVATE KEY-----",
            following="b3BlbnNzaC1rZXktdjEAAAAABG5vbmUAAAAEbm9uZQAAAAAAAAAB",
        )
        is True
    )


def test_a_long_unfamiliar_value_still_gets_through():
    assert is_worth_reporting(UNFAMILIAR_LINE) is True


def test_a_catalog_label_about_a_password_is_prose_not_a_value():
    line = '  "ui.login.password_label": "Panel password",'
    assert is_catalog_line("hub/frontend/src/locales/en/login.json", line)
    assert (
        is_worth_reporting(line, path="hub/frontend/src/locales/en/login.json") is False
    )
    # The same shape outside a catalog, or a catalog value with no space and a
    # credential's length, is still shown.
    assert is_catalog_line("hub/neutrino_hub/data/examples/web.json", line) is False
    long_value = '  "ui.login.password_label": "sk-ant-a-very-long-token-value-here",'  # scan: allow
    assert (
        is_catalog_line("hub/frontend/src/locales/en/login.json", long_value) is False
    )


def test_a_chinese_catalog_value_is_prose_without_a_space():
    chinese = '  "ui.samba.password_failure": "密码未设置：{failures}",'
    assert is_catalog_line("hub/frontend/src/locales/zh-CN/modules.json", chinese)

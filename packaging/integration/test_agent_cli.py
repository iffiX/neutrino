"""nagent's whole verb tree, on a live device against a live hub.

The device is whatever the environment names: a client VM on the lab wire, a
rented Windows Server, a rented Mac. Every check drives it the way a person
would, ``nagent`` over SSH, and reads the answer off two surfaces that must
agree: the command's own output and the hub's view of the same machine.

Every module the catalog offers this platform is walked. The ones the hub
installs are installed and uninstalled for real; the one the platform
carries is switched where that is reversible; the ones a vendor installs are
asked for and must be refused; the SSH server, which is the door these
checks come in through, is left installed and its guard is what is tested.

Environment:

    NEUTRINO_DEVICE_HOST      where the device answers SSH
    NEUTRINO_DEVICE_USER      the account to log in as
    NEUTRINO_DEVICE_KEY       the private key
    NEUTRINO_DEVICE_PLATFORM  linux, windows or darwin
    NEUTRINO_DEVICE_NAME      what the hub calls the device

Without a device the file skips. The file order is the run order: the
modules a later check needs are installed by an earlier one and removed by
the last.
"""

import json
import os
import shlex
import subprocess
import tempfile
import time

import pytest

DEVICE_TIMEOUT_S = 120
MODULE_TIMEOUT_S = 600
HUB_TASK_TIMEOUT_S = 600
MOUNT_TIMEOUT_S = 90

NAGENT_WINDOWS = r"C:\Program Files\Neutrino Agent\nagent.cmd"
DEVICE_NAME_ENV = "NEUTRINO_DEVICE_NAME"

# The state words the page and the CLI share, the closed set.
STATE_WORDS = (
    "installed",
    "not installed",
    "installing",
    "uninstalling",
    "not available on this machine",
    "failed",
    "waiting for the agent",
)

SHARE_NAME = "integration"
SHARE_USER = "integration"
SHARE_PASSWORD = "share-for-the-walk"  # scan: allow
MOUNT_PATH = {
    "linux": "/mnt/neutrino_integration",
    "darwin": "/Volumes/neutrino_integration",
    "windows": "N:",
}
DECLARED_PORT_NAME = "cli walk panel port"
DECLARED_WEB_NAME = "cli walk panel link"


def wait_for(what, predicate, timeout_s):
    deadline = time.monotonic() + timeout_s
    while True:
        value = predicate()
        if value:
            return value
        if time.monotonic() >= deadline:
            raise AssertionError(f"timed out waiting for {what}")
        time.sleep(3)


class Device:
    """One device, driven over SSH the way a person at it would drive it."""

    def __init__(self, *, host, user, key, platform):
        self.host = host
        self.user = user
        self.key = key
        self.platform = platform
        self.control_dir = tempfile.mkdtemp(prefix="nagent_walk_")

    def shell(self, command, *, stdin=None, timeout_s=DEVICE_TIMEOUT_S):
        """Run one command in the device's own login shell.

        On Windows that shell is PowerShell, the way the harness set sshd up.
        A connection reset is retried: many short connections in a row trip
        Windows sshd's start limit, and a reset is the transport, not the
        answer.
        """
        for attempt in range(3):
            result = self._ssh(command, stdin=stdin, timeout_s=timeout_s)
            if result.returncode != 255:
                return result
            time.sleep(3 * (attempt + 1))
        return result

    def _ssh(self, command, *, stdin, timeout_s):
        # One connection for the whole walk, multiplexed: dozens of fresh
        # SSH connections a minute to one host read as a brute-force burst
        # to whatever sits on the path, which answers with resets.
        return subprocess.run(
            [
                "ssh",
                "-o",
                "ControlMaster=auto",
                "-o",
                f"ControlPath={self.control_dir}/%C",
                "-o",
                "ControlPersist=180",
                "-i",
                self.key,
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=no",
                "-o",
                "UserKnownHostsFile=/dev/null",
                "-o",
                "LogLevel=ERROR",
                "-o",
                "ConnectTimeout=10",
                f"{self.user}@{self.host}",
                command,
            ],
            capture_output=True,
            text=True,
            input=stdin,
            timeout=timeout_s,
        )

    def nagent(self, *args, stdin=None, timeout_s=DEVICE_TIMEOUT_S):
        """Run ``nagent`` with the privilege a person would give it.

        Root on the POSIX platforms, where the binding is root's; the
        administrator's own SSH session on Windows, which is elevated.
        """
        if self.platform == "windows":
            quoted = " ".join(_powershell_quote(arg) for arg in args)
            # PowerShell folds a native command's exit code into 1 unless it
            # is handed back on purpose, and the walk reads 2 for "no such".
            command = (
                f"& {_powershell_quote(NAGENT_WINDOWS)} {quoted}; exit $LASTEXITCODE"
            )
        else:
            command = "sudo nagent " + shlex.join(args)
        return self.shell(command, stdin=stdin, timeout_s=timeout_s)

    def fetch_status(self, url):
        """The HTTP status the device itself gets for a URL."""
        if self.platform == "windows":
            result = self.shell(
                "try { (Invoke-WebRequest -UseBasicParsing "
                + _powershell_quote(url)
                + ").StatusCode } catch { $_.Exception.Response.StatusCode.value__ }"
            )
        else:
            result = self.shell(
                f"curl -s -o /dev/null -w '%{{http_code}}' {shlex.quote(url)}"
            )
        return result.stdout.strip()

    def listing(self, path):
        """The names inside a directory, empty when it cannot be read."""
        if self.platform == "windows":
            result = self.shell(
                f"Get-ChildItem -Name {_powershell_quote(path + chr(92))} "
                "-ErrorAction SilentlyContinue"
            )
        else:
            result = self.shell(f"ls -1 {shlex.quote(path)} 2>/dev/null")
        return result.stdout.split()

    def write_file(self, path, name):
        if self.platform == "windows":
            return self.shell(
                f"Set-Content -Path {_powershell_quote(path + chr(92) + name)} "
                f"-Value 'written by the walk'"
            )
        return self.shell(
            f"sudo sh -c 'echo written by the walk > {shlex.quote(path + '/' + name)}'"
        )


def _powershell_quote(text):
    return "'" + str(text).replace("'", "''") + "'"


@pytest.fixture(scope="module")
def device():
    host = os.environ.get("NEUTRINO_DEVICE_HOST", "")
    if not host:
        pytest.skip("no device: set NEUTRINO_DEVICE_HOST and its siblings")
    platform = os.environ.get("NEUTRINO_DEVICE_PLATFORM", "linux")
    assert platform in MOUNT_PATH, f"unknown platform {platform!r}"
    return Device(
        host=host,
        user=os.environ.get("NEUTRINO_DEVICE_USER", "root"),
        key=os.environ["NEUTRINO_DEVICE_KEY"],
        platform=platform,
    )


@pytest.fixture(scope="module")
def device_name():
    name = os.environ.get(DEVICE_NAME_ENV, "")
    if not name:
        pytest.skip(f"set ${DEVICE_NAME_ENV} to what the hub calls the device")
    return name


@pytest.fixture(scope="module")
def mac(panel, device_name):
    """The device's identity on the hub, found by the name it enrolled as."""
    row = wait_for(
        f"the hub to list {device_name}",
        lambda: _device_row(panel, device_name),
        DEVICE_TIMEOUT_S,
    )
    return row["mac_address"]


def _device_row(panel, name):
    view = panel.read("/devices")
    for row in view.get("devices", []):
        if row.get("name") == name:
            return row
    return None


def hub_modules(panel, mac):
    """The hub's rows for the device, by module name."""
    view = panel.read(f"/devices/{mac}/modules")
    assert view.get("is_agent_online"), view
    return {row["name"]: row for row in view.get("modules", [])}


def cli_modules(device):
    """The CLI's rows, by module name, each with its state words."""
    listed = device.nagent("module", "list")
    assert listed.returncode == 0, listed.stdout + listed.stderr
    rows = {}
    for line in listed.stdout.splitlines():
        parts = line.split("  ")
        parts = [part.strip() for part in parts if part.strip()]
        if len(parts) >= 2:
            rows[parts[0]] = parts[1:]
    return rows


def wait_module_state(device, panel, mac, name, state, timeout_s=MODULE_TIMEOUT_S):
    """Both surfaces agreeing on one module's state."""

    def agreed():
        hub_state = hub_modules(panel, mac).get(name, {}).get("state")
        cli_words = " ".join(cli_modules(device).get(name, []))
        cli_state = _state_of(cli_words)
        return hub_state == state and cli_state == state

    wait_for(f"{name} to read {state} on both surfaces", agreed, timeout_s)


def _state_of(words):
    for token, word in (
        ("installed", "installed"),
        ("absent", "not installed"),
        ("installing", "installing"),
        ("uninstalling", "uninstalling"),
        ("unsupported", "not available on this machine"),
        ("failed", "failed"),
    ):
        if words.startswith(word) or f"  {word}" in words or f" {word}" in words:
            if token == "installed" and "not installed" in words:
                continue
            return token
    return ""


# --- status ----------------------------------------------------------------


def test_status_reports_the_hub_and_a_good_heartbeat(device):
    answer = device.nagent("status")

    assert answer.returncode == 0, answer.stdout + answer.stderr
    assert "connected" in answer.stdout
    assert "heartbeat  ok" in answer.stdout


# --- modules ---------------------------------------------------------------


def test_module_list_names_every_module_the_catalog_offers(device, panel, mac):
    """The CLI's rows are the hub's rows, in the hub's order, and every state
    is one of the closed set of words."""
    listed = device.nagent("module", "list")
    assert listed.returncode == 0, listed.stdout + listed.stderr

    hub_rows = hub_modules(panel, mac)
    cli_rows = cli_modules(device)
    assert list(cli_rows) == list(hub_rows), (list(cli_rows), list(hub_rows))
    for name, words in cli_rows.items():
        joined = " ".join(words)
        assert any(word in joined for word in STATE_WORDS + ("built in",)), (
            name,
            joined,
        )


def test_the_ssh_server_is_installed_and_its_uninstall_is_guarded(device, panel, mac):
    """These checks come in through it. It reads installed on both surfaces,
    and uninstalling it asks first; declining changes nothing."""
    assert hub_modules(panel, mac)["ssh_server"]["state"] == "installed"

    declined = device.nagent("module", "uninstall", "ssh_server", stdin="n\n")

    assert declined.returncode == 1, declined.stdout + declined.stderr
    assert "nothing was changed" in declined.stdout
    assert hub_modules(panel, mac)["ssh_server"]["state"] == "installed"


@pytest.mark.parametrize("name", ["anydesk", "teamviewer"])
def test_a_vendor_installed_module_takes_no_order(device, panel, mac, name):
    """The person installs those; the hub only detects them. An install ask
    is refused on the CLI, and the hub's row stays exactly where it was."""
    before = hub_modules(panel, mac)[name]
    assert before["installer"] == "user"

    asked = device.nagent("module", "install", name, "--no-wait")

    assert asked.returncode != 0, asked.stdout + asked.stderr
    assert hub_modules(panel, mac)[name]["state"] == before["state"]


def test_the_platforms_own_mount_tooling_is_native_or_installable(device, panel, mac):
    """samba_mount is the platform tier: built in where the OS mounts SMB
    itself, a package where it does not. Both read the same on both
    surfaces, and the package one installs and uninstalls."""
    row = hub_modules(panel, mac)["samba_mount"]
    assert row["installer"] == "platform"
    if row["is_native"]:
        told = device.nagent("module", "install", "samba_mount")
        assert told.returncode == 0, told.stdout + told.stderr
        assert "built in" in told.stdout
        return
    if row["state"] != "installed":
        installed = device.nagent(
            "module", "install", "samba_mount", timeout_s=MODULE_TIMEOUT_S
        )
        assert installed.returncode == 0, installed.stdout + installed.stderr
        assert "done" in installed.stdout
    wait_module_state(device, panel, mac, "samba_mount", "installed")


@pytest.mark.parametrize("name", ["cc_switch", "rustdesk"])
def test_a_hub_installed_module_installs_through_the_hub(device, panel, mac, name):
    """The hub fetches the pinned artifact and the agent installs it; the
    CLI follows the operation to done, and both surfaces read installed.
    Left installed: the checks below use them."""
    if hub_modules(panel, mac)[name]["state"] == "installed":
        # Left behind by a walk that stopped early. Removed first, so this
        # walk installs for real rather than reading someone else's result.
        removed = device.nagent("module", "uninstall", name, timeout_s=MODULE_TIMEOUT_S)
        assert removed.returncode == 0, removed.stdout + removed.stderr
        wait_module_state(device, panel, mac, name, "absent")

    installed = device.nagent("module", "install", name, timeout_s=MODULE_TIMEOUT_S)

    assert installed.returncode == 0, installed.stdout + installed.stderr
    assert "done" in installed.stdout
    wait_module_state(device, panel, mac, name, "installed")


def test_an_installed_module_is_already_installed(device):
    told = device.nagent("module", "install", "cc_switch")

    assert told.returncode == 0, told.stdout + told.stderr
    assert "already installed" in told.stdout


def test_a_module_the_list_lacks_is_named_back(device):
    asked = device.nagent("module", "install", "no_such_module")

    assert asked.returncode == 2, asked.stdout + asked.stderr
    assert "no module named no_such_module" in asked.stderr


def test_operation_reports_the_last_order(device):
    """The last install is the last operation, and it reads done."""
    reported = device.nagent("operation")

    assert reported.returncode == 0, reported.stdout + reported.stderr
    assert "done" in reported.stdout


# --- services --------------------------------------------------------------


@pytest.fixture(scope="module")
def declared(panel):
    """A port and a link the hub publishes for the walk: its own panel."""
    import urllib.parse

    split = urllib.parse.urlsplit(panel.base_url)
    port = split.port or 80
    # Loopback rather than the panel's own address: the hub probes it from
    # itself, and hands the device the address that device reached the hub
    # on, which is the one address both of them can agree is the hub.
    host = "127.0.0.1"
    made = []
    for body in (
        {"name": DECLARED_PORT_NAME, "kind": "port", "host": host, "port": port},
        {
            "name": DECLARED_WEB_NAME,
            "kind": "web",
            "host": host,
            "port": port,
            "scheme": "http",
            "path": "/",
        },
    ):
        status, view = panel.call("POST", "/services/declared", body)
        assert status == 201, view
        record_id = next(
            entry["record_id"]
            for entry in view["services"]
            if entry.get("source") == "declared" and entry["title"] == body["name"]
        )
        made.append(record_id)
        # Probed now rather than on the hub's own schedule: a device is
        # handed the entry unhealthy until the first probe answers.
        panel.call("POST", f"/services/declared/{record_id}/probe")
    yield {"port": port, "host": host}
    for record_id in made:
        panel.call("DELETE", f"/services/declared/{record_id}")


def service_rows(device):
    """The CLI's nested list: kind heading to its numbered rows."""
    listed = device.nagent("service", "list")
    assert listed.returncode == 0, listed.stdout + listed.stderr
    rows = {}
    heading = None
    for line in listed.stdout.splitlines():
        if not line.startswith(" ") and line.strip():
            heading = line.strip()
            rows[heading] = []
        elif heading and line.startswith("  ") and line.strip()[:1].isdigit():
            rows[heading].append(line.strip())
    return rows


def wait_service_row(
    device, heading_word, title, timeout_s=DEVICE_TIMEOUT_S, is_healthy=False
):
    """The row for one published entry, once the device has been served it.

    With ``is_healthy`` the row must also carry no reachability note: the
    verbs that use an entry refuse one the hub last found unreachable.
    """

    def found():
        for heading, rows in service_rows(device).items():
            if heading_word not in heading.lower():
                continue
            for row in rows:
                if title in row and not (is_healthy and "not reachable" in row):
                    return row
        return None

    return wait_for(f"{title} under {heading_word}", found, timeout_s)


def test_service_list_is_nested_by_kind_and_numbered(device, declared):
    port_row = wait_service_row(device, "port", DECLARED_PORT_NAME)
    web_row = wait_service_row(device, "web", DECLARED_WEB_NAME)

    assert port_row.split()[0].isdigit(), port_row
    assert web_row.split()[0].isdigit(), web_row
    assert f":{declared['port']}" in port_row


def test_a_port_forward_carries_the_panel_to_the_device(device, declared):
    """Forwarding a published port opens a loopback port on the device that
    reaches the hub's panel; unforwarding closes it."""
    row = wait_service_row(device, "port", DECLARED_PORT_NAME, is_healthy=True)
    number = row.split()[0]

    forwarded = device.nagent("service", "port", "forward", number)
    assert forwarded.returncode == 0, forwarded.stdout + forwarded.stderr
    local = forwarded.stdout.strip().splitlines()[-1]
    assert local.startswith("127.0.0.1:"), local

    try:
        status = wait_for(
            "the forward to answer",
            lambda: device.fetch_status(f"http://{local}/") in ("200", "302", "303"),
            DEVICE_TIMEOUT_S,
        )
        assert status
    finally:
        closed = device.nagent("service", "port", "unforward", number)
    assert closed.returncode == 0, closed.stdout + closed.stderr
    assert "closed" in closed.stdout


def test_web_open_names_the_link(device, declared):
    """Headless, so the browser is not what is checked: the verb resolves
    the entry, prints the link it is opening, and exits clean."""
    row = wait_service_row(device, "web", DECLARED_WEB_NAME, is_healthy=True)
    number = row.split()[0]

    opened = device.nagent("service", "web", "open", number)

    assert opened.returncode == 0, opened.stdout + opened.stderr
    assert "opening http://" in opened.stdout


@pytest.fixture(scope="module")
def share(panel):
    """A share on the hub, with one user who may reach it."""
    if not _module_present(panel, "samba"):
        status, started = panel.call("POST", "/modules/samba/install", {})
        assert status in (200, 202), started
        wait_for(
            "samba to install on the hub",
            lambda: _module_present(panel, "samba"),
            HUB_TASK_TIMEOUT_S,
        )
    status, users = panel.call("PUT", "/samba/users", {"users": [SHARE_USER]})
    assert status == 200, users
    status, shares = panel.call(
        "PUT",
        "/samba/shares",
        {
            "shares": [
                {
                    "name": SHARE_NAME,
                    "path": f"/srv/{SHARE_NAME}",
                    "comment": "the CLI walk's share",
                    "is_read_only": False,
                    "valid_users": [SHARE_USER],
                }
            ]
        },
    )
    assert status == 200, shares
    # Apply creates the account; the password is set on the account it made.
    status, applied = panel.call("POST", "/samba/apply", {})
    assert status == 200, applied
    status, set_password = panel.call(
        "POST", f"/samba/users/{SHARE_USER}/password", {"password": SHARE_PASSWORD}
    )
    assert status == 200, set_password
    yield SHARE_NAME
    panel.call("PUT", "/samba/shares", {"shares": []})
    panel.call("PUT", "/samba/users", {"users": []})
    panel.call("POST", "/samba/apply", {})


def _module_present(panel, name):
    view = panel.read("/modules")
    for row in view.get("modules", []):
        if row.get("name") == name:
            return bool(row.get("is_installed"))
    return False


def test_a_share_mounts_writes_survive_a_remount_and_it_unmounts(
    device, panel, mac, share
):
    """config saves the login and mounts; a file written through the mount
    is there after unmount and mount; unmount leaves the record detached."""
    row = wait_service_row(device, "file", share, is_healthy=True)
    number = row.split()[0]
    path = MOUNT_PATH[device.platform]

    configured = device.nagent(
        "service",
        "file",
        "config",
        number,
        "--path",
        path,
        "--username",
        SHARE_USER,
        stdin=SHARE_PASSWORD + "\n",
        timeout_s=MOUNT_TIMEOUT_S,
    )
    assert configured.returncode == 0, configured.stdout + configured.stderr

    def mounted():
        listed = device.nagent("service", "list").stdout
        return "mounted" in listed and "not mounted" not in listed

    def record():
        view = panel.read(f"/devices/{mac}/services")
        for row in view.get("mounts", []):
            if row.get("path") == path and row.get("state") in ("mounted", "failed"):
                return row
        return None

    # The hub's record is the typed answer; the CLI's line is its wording,
    # and the two must agree.
    outcome = wait_for("the share to mount or refuse", record, MOUNT_TIMEOUT_S)
    if outcome["state"] == "failed":
        # Windows maps a drive inside the account's own logged-on session,
        # and a box reached only over SSH has none. The refusal is the
        # platform's honest answer, worded on the CLI; the mount itself
        # needs a seat.
        assert outcome["code"] == "no_logged_on_session", outcome
        listed = device.nagent("service", "list").stdout
        assert "sign in as the mount's account on this machine" in listed, listed
        device.nagent("service", "file", "unmount", number, timeout_s=MOUNT_TIMEOUT_S)
        pytest.skip(
            "mounting needs a logged-on session here; the refusal was typed and worded"
        )
    wait_for("the share to read mounted on the CLI", mounted, MOUNT_TIMEOUT_S)
    written = device.write_file(path, "walk.txt")
    assert written.returncode == 0, written.stdout + written.stderr
    assert "walk.txt" in device.listing(path)

    unmounted = device.nagent(
        "service", "file", "unmount", number, timeout_s=MOUNT_TIMEOUT_S
    )
    assert unmounted.returncode == 0, unmounted.stdout + unmounted.stderr
    wait_for(
        "the share to unmount",
        lambda: "not mounted" in device.nagent("service", "list").stdout,
        MOUNT_TIMEOUT_S,
    )
    assert "walk.txt" not in device.listing(path)

    remounted = device.nagent(
        "service", "file", "mount", number, timeout_s=MOUNT_TIMEOUT_S
    )
    assert remounted.returncode == 0, remounted.stdout + remounted.stderr
    wait_for("the share to mount again", mounted, MOUNT_TIMEOUT_S)
    assert "walk.txt" in device.listing(path)

    device.nagent("service", "file", "unmount", number, timeout_s=MOUNT_TIMEOUT_S)


# --- the AI gateway --------------------------------------------------------


@pytest.fixture(scope="module")
def ai_provider(panel):
    """A keyed provider on the hub, which is what makes the gateway served.

    The key is a placeholder: the walk switches accounts at the gateway and
    reads their standing back, it does not complete a model call.
    """
    status, token = panel.call(
        "POST", "/credentials/tokens", {"name": "cli walk key", "value": "walk-key"}
    )
    assert status in (200, 201), token
    status, provider = panel.call(
        "POST",
        "/ai/providers",
        {
            "name": "cli walk provider",
            "kind": "custom",
            "base_url": "http://127.0.0.1:9/v1",
            "secret_id": token["id"],
            "models": [{"name": "walk-model", "alias": "walk"}],
        },
    )
    assert status in (200, 201), provider
    yield provider
    panel.call("DELETE", f"/ai/providers/{provider['id']}")
    panel.call("DELETE", f"/credentials/tokens/{token['id']}")


def ai_rows(device):
    """Each account's switch and standing, from ``service ai show``."""
    shown = device.nagent("service", "ai", "show")
    assert shown.returncode == 0, shown.stdout + shown.stderr
    rows = {}
    for line in shown.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] in ("on", "off"):
            rows[parts[0]] = (parts[1], " ".join(parts[2:]))
    return rows


def test_ai_show_lists_every_account_with_its_standing(device, ai_provider):
    wait_service_row(device, "ai", "")
    rows = wait_for(
        "accounts under the AI entry", lambda: ai_rows(device), DEVICE_TIMEOUT_S
    )

    assert rows, rows
    assert all(switch == "off" for switch, _ in rows.values()), rows


def test_ai_apply_switches_one_account_on_and_the_rest_back(device, ai_provider):
    """The named set is the whole enabled set: one account on, then none."""
    account = next(iter(ai_rows(device)))

    applied = device.nagent(
        "service", "ai", "apply", "--account", account, timeout_s=MOUNT_TIMEOUT_S
    )
    assert applied.returncode == 0, applied.stdout + applied.stderr
    wait_for(
        f"{account} to read on",
        lambda: ai_rows(device).get(account, ("", ""))[0] == "on",
        MOUNT_TIMEOUT_S,
    )

    cleared = device.nagent("service", "ai", "apply", timeout_s=MOUNT_TIMEOUT_S)
    assert cleared.returncode == 0, cleared.stdout + cleared.stderr
    wait_for(
        f"{account} to read off again",
        lambda: ai_rows(device).get(account, ("", ""))[0] == "off",
        MOUNT_TIMEOUT_S,
    )


# --- remote desktop --------------------------------------------------------


def test_rdp_show_reads_not_shared(device):
    """A share left up by a walk that stopped early is taken down first, so
    this reads the box's own answer rather than an earlier run's."""
    shown = device.nagent("service", "rdp", "show")
    assert shown.returncode == 0, shown.stdout + shown.stderr
    if "not shared" not in shown.stdout:
        device.nagent("service", "rdp", "unshare", timeout_s=MOUNT_TIMEOUT_S)
        shown = device.nagent("service", "rdp", "show")

    assert "not shared" in shown.stdout, shown.stdout


def test_rdp_share_answers_the_way_the_platform_can(device):
    """A rented box reached over SSH has nobody at its screen. On Windows
    RustDesk runs as a service and shares the sign-in screen anyway, so the
    share goes through and comes back down; on the POSIX platforms a share
    is one seat's, and without one the refusal is typed and worded."""
    asked = device.nagent(
        "service", "rdp", "share", stdin="walk-password\n", timeout_s=MOUNT_TIMEOUT_S
    )

    if device.platform == "windows":
        assert asked.returncode == 0, asked.stdout + asked.stderr
        assert "shared" in asked.stdout and ":21118" in asked.stdout, asked.stdout
        shown = device.nagent("service", "rdp", "show")
        assert (
            "shared" in shown.stdout and "not shared" not in shown.stdout
        ), shown.stdout
        down = device.nagent("service", "rdp", "unshare", timeout_s=MOUNT_TIMEOUT_S)
        assert down.returncode == 0, down.stdout + down.stderr
        assert "not shared" in device.nagent("service", "rdp", "show").stdout
        return
    assert asked.returncode != 0, asked.stdout + asked.stderr
    assert "desktop" in asked.stderr.lower() or "signed in" in asked.stderr.lower(), (
        asked.stdout + asked.stderr
    )


# --- and back --------------------------------------------------------------


@pytest.mark.parametrize("name", ["rustdesk", "cc_switch"])
def test_a_hub_installed_module_uninstalls_through_the_hub(device, panel, mac, name):
    removed = device.nagent("module", "uninstall", name, timeout_s=MODULE_TIMEOUT_S)

    assert removed.returncode == 0, removed.stdout + removed.stderr
    assert "done" in removed.stdout
    wait_module_state(device, panel, mac, name, "absent")


def test_the_hub_and_the_cli_agree_on_every_row_at_the_end(device, panel, mac):
    hub_rows = hub_modules(panel, mac)
    cli_rows = cli_modules(device)

    for name, row in hub_rows.items():
        words = " ".join(cli_rows.get(name, []))
        if row.get("is_native"):
            assert "built in" in words, (name, words)
            continue
        assert _state_of(words) == row["state"], (name, words, row["state"])

"""What SiYuan adds to the shared runner: each account's kernel, its settings, its login.

The publisher's desktop build comes down the hub's package stream as the
module's ``app`` artifact and lands under that directory in the module's
own, never on a ``PATH``. Each instance runs the build's kernel as its
account under ``umask 077``, on a loopback port the agent picks and keeps in
the record, with its workspace and its own files in the account's data
directory, which the hook makes as the account, and its access code in a
root-only environment. Before the forwarder listens the hook writes the
module's provider into the workspace's ``conf.json`` as the account, with
the kernel stopped, whenever the key, the gateway's address or the models
differ from what the record says was written. The forwarder trades the
hub's token for the kernel's own login, which it asks for itself, and the
browser keeps the kernel's cookie under the entry's ``cookie_name``.

Not pure: runs as the account, drives the account's service, talks to the
kernel.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import http.client
import json
import ntpath
import os
import socket
import subprocess
import urllib.parse

from neutrino_agent.constants import AGENT_FORWARD_UPSTREAM_TIMEOUT_S
from neutrino_agent.exceptions import ModuleApplyError, PlatformUnsupportedError
from neutrino_agent.modules.shared import account_service
from neutrino_agent.modules.shared.account_service import (
    AccountEntry,
    AccountService,
)
from neutrino_agent.modules.shared.http_forward import (
    RELAY,
    ForwardDecision,
    answered,
    refused,
)
from neutrino_agent.modules.shared.instances import InstanceHooks
from neutrino_agent.modules.siyuan.config import (
    SiyuanConfig,
    SiyuanInstance,
    settings_digest,
    with_module_settings,
)
from neutrino_agent.modules.siyuan.constants import (
    SIYUAN_ACCOUNT_STEP_TIMEOUT_S,
    SIYUAN_APP_DIR_NAME,
    SIYUAN_BASE_PORT,
    SIYUAN_CONF_PARTS,
    SIYUAN_COOKIE,
    SIYUAN_DATA_PARTS,
    SIYUAN_ENV_ACCESS_CODE,
    SIYUAN_ENV_DATA,
    SIYUAN_ENV_PORT,
    SIYUAN_ENV_WORKSPACE,
    SIYUAN_FLAG_HOME_DIR,
    SIYUAN_FLAG_PORT,
    SIYUAN_FLAG_WD,
    SIYUAN_FLAG_WORKSPACE,
    SIYUAN_FORWARDER_FIELDS,
    SIYUAN_HOME_PATH,
    SIYUAN_KERNEL_PARTS,
    SIYUAN_LOGIN_PATH,
    SIYUAN_NAME,
    SIYUAN_PACKAGE_PARTS,
    SIYUAN_POSIX_MKDIR_SHELL,
    SIYUAN_POSIX_WRITE_SHELL,
    SIYUAN_RECORD_FIELDS,
    SIYUAN_RESOURCES_PARTS,
    SIYUAN_RUNNER,
    SIYUAN_SERVE,
    SIYUAN_TITLE,
    SIYUAN_UMASK,
    SIYUAN_UPSTREAM_HOST,
    SIYUAN_WORKSPACE_NAME,
)


def data_dir(home: str, os_name: str, join=os.path.join) -> str:
    """One account's SiYuan data directory, under its home.

    Args:
        home: The account's home.
        os_name: The system.
        join: How the system joins a path.

    Returns:
        The directory ``--home-dir`` names, the workspace under it.
    """
    return join(home, *SIYUAN_DATA_PARTS[os_name])


def service_command(
    kernel: str, *, resources: str, data: str, kernel_port: int, os_name: str, join
) -> tuple:
    """The kernel's command line for one instance.

    Args:
        kernel: The kernel's path.
        resources: Its working directory.
        data: The account's data directory.
        kernel_port: The loopback port the kernel listens on.
        os_name: The system; on Linux one template unit runs every account,
            so the data directory and the port come from the instance's
            environment.
        join: How the system joins a path.

    Returns:
        ``<kernel> serve --wd=<resources> --workspace=<data>/workspace
        --home-dir=<data> --port=<kernel port>``.
    """
    if os_name == "linux":
        workspace = f"${{{SIYUAN_ENV_WORKSPACE}}}"
        home_dir = f"${{{SIYUAN_ENV_DATA}}}"
        port = f"${{{SIYUAN_ENV_PORT}}}"
    else:
        workspace = join(data, SIYUAN_WORKSPACE_NAME)
        home_dir = data
        port = str(int(kernel_port))
    return (
        kernel,
        SIYUAN_SERVE,
        SIYUAN_FLAG_WD + resources,
        SIYUAN_FLAG_WORKSPACE + workspace,
        SIYUAN_FLAG_HOME_DIR + home_dir,
        SIYUAN_FLAG_PORT + port,
    )


def service_environment(
    access_code: str, *, data: str, kernel_port: int, os_name: str, join
) -> dict:
    """The environment one instance's kernel runs with, written from scratch.

    Args:
        access_code: The kernel's access code.
        data: The account's data directory.
        kernel_port: The loopback port the kernel listens on.
        os_name: The system.
        join: How the system joins a path.

    Returns:
        The access code; on Linux also the workspace, the data directory
        and the port its command line names.
    """
    environment = {SIYUAN_ENV_ACCESS_CODE: access_code}
    if os_name == "linux":
        environment[SIYUAN_ENV_WORKSPACE] = (
            join(data, SIYUAN_WORKSPACE_NAME) if data else ""
        )
        environment[SIYUAN_ENV_DATA] = data
        environment[SIYUAN_ENV_PORT] = str(int(kernel_port or 0))
    return environment


def normal_path(path: str) -> str:
    """A path as the kernel's router matches it, lower case: decoded, slashes collapsed, none at its end."""
    decoded = urllib.parse.unquote(path).lower()
    while "//" in decoded:
        decoded = decoded.replace("//", "/")
    return decoded.rstrip("/") or "/"


def page_cookie(headers: list) -> str:
    """The ``Set-Cookie`` the kernel's login answer carries its own cookie in.

    Args:
        headers: ``(name, value)`` of the answer.

    Returns:
        The header's value, empty when the answer sets no such cookie.
    """
    for name, value in headers:
        if name.lower() != "set-cookie":
            continue
        if value.split("=", 1)[0].strip() == SIYUAN_COOKIE:
            return value
    return ""


def kernel_login(port: int, host: str, access_code: str) -> tuple:
    """The kernel's answer to the forwarder's own login, with the browser's ``Host`` and no ``Origin``.

    Args:
        port: The kernel's loopback port.
        host: The ``Host`` the browser sent.
        access_code: The kernel's access code.

    Returns:
        ``(status, body, headers)``, the body parsed, the headers as
        ``(name, value)`` pairs.

    Raises:
        OSError: When the kernel does not answer.
    """
    connection = http.client.HTTPConnection(
        SIYUAN_UPSTREAM_HOST, port, timeout=AGENT_FORWARD_UPSTREAM_TIMEOUT_S
    )
    body = json.dumps({"authCode": access_code, "rememberMe": True}).encode("utf-8")
    try:
        connection.putrequest("POST", SIYUAN_LOGIN_PATH, skip_host=True)
        connection.putheader("Host", host or f"{SIYUAN_UPSTREAM_HOST}:{port}")
        connection.putheader("Content-Type", "application/json")
        connection.putheader("Content-Length", str(len(body)))
        connection.endheaders(body)
        response = connection.getresponse()
        raw = response.read()
        try:
            parsed = json.loads(raw.decode("utf-8") or "{}")
        except ValueError:
            parsed = {}
        return int(response.status), parsed, list(response.getheaders())
    except http.client.HTTPException as error:
        raise ConnectionError(str(error)) from error
    finally:
        connection.close()


def free_loopback_port() -> int:
    """A port nothing listens on at the loopback address, as the system picks one.

    Returns:
        The port.

    Raises:
        OSError: When the system gives none.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind((SIYUAN_UPSTREAM_HOST, 0))
        return int(probe.getsockname()[1])


def installed_version(resources: str, join=os.path.join) -> str:
    """The desktop build's version, from its own description.

    Args:
        resources: The kernel's working directory.
        join: How the system joins a path.

    Returns:
        Its ``version``, empty when it cannot be read.
    """
    try:
        with open(join(resources, *SIYUAN_PACKAGE_PARTS), encoding="utf-8") as stream:
            held = json.load(stream)
    except (OSError, ValueError):
        return ""
    return str(held.get("version", "") or "") if isinstance(held, dict) else ""


def _step_read(path: str) -> "str | None":
    """A file's text, None when it cannot be read."""
    try:
        with open(path, "r", encoding="utf-8") as stream:
            return stream.read()
    except OSError:
        return None


def _step_write(path: str, text: str) -> str:
    """Write a file whole through one beside it; what failed, empty when written."""
    temporary = path + ".neutrino"
    try:
        with open(temporary, "w", encoding="utf-8") as stream:
            stream.write(text)
        os.replace(temporary, path)
    except OSError as error:
        return str(error)
    return ""


def _step_make_dir(path: str) -> str:
    """Make a directory with its parents; what failed, empty when made."""
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as error:
        return str(error)
    return ""


class SiyuanHooks(InstanceHooks):
    """SiYuan's part of the shared runner."""

    name = SIYUAN_NAME
    title = SIYUAN_TITLE
    runner = SIYUAN_RUNNER
    instance_class = SiyuanInstance
    record_fields = SIYUAN_RECORD_FIELDS
    forwarder_fields = SIYUAN_FORWARDER_FIELDS
    secret_field = "secret"
    base_port = SIYUAN_BASE_PORT
    page_cookie = SIYUAN_COOKIE

    def __init__(self, *, platform, log=print, pick_port=None, login=None):
        """
        Args:
            platform: The machine's platform, which runs steps as an account.
            log: Callable used for progress messages.
            pick_port: Returns a free loopback port for a new kernel; None
                asks the system.
            login: Called as :func:`kernel_login`; None asks the kernel.
        """
        super().__init__(platform=platform, log=log)
        self._pick_port = pick_port if pick_port is not None else free_loopback_port
        self._login = login if login is not None else kernel_login
        # Account to the settings this agent last wrote for it, so a
        # forwarder that started from an older record writes them once.
        self._written: dict = {}

    @property
    def resources_dir(self) -> str:
        """The kernel's working directory inside the ``app`` artifact."""
        return self._join(
            self.machine.module_dir,
            SIYUAN_APP_DIR_NAME,
            *SIYUAN_RESOURCES_PARTS[self._os_name],
        )

    @property
    def kernel_path(self) -> str:
        """The kernel inside the ``app`` artifact."""
        return self._join(self.resources_dir, *SIYUAN_KERNEL_PARTS[self._os_name])

    def parse(self, config: dict) -> SiyuanConfig:
        """The configuration parsed and checked for this system.

        Args:
            config: The module's desired configuration.

        Returns:
            The configuration.

        Raises:
            ModuleApplyError: ``account_invalid``, ``account_duplicate`` or
                ``secret_missing``, naming the first problem found, and on
                Windows ``credential_missing``.
        """
        parsed = SiyuanConfig.from_dict(config)
        parsed.validate(os_name=self._os_name)
        return parsed

    def verify(self) -> bool:
        """Whether the kernel's file exists."""
        return os.path.isfile(self.kernel_path)

    def prepare(
        self, parsed: SiyuanConfig, instance: SiyuanInstance, entry: AccountEntry
    ) -> list:
        """Make the account's workspace as the account, unless it is there.

        The kernel takes a workspace that does not exist as a reason to use
        another, so the directory is made before its first start.

        Args:
            parsed: The configuration.
            instance: The instance.
            entry: Its account.

        Returns:
            One note when the workspace was made.

        Raises:
            ModuleApplyError: ``apply_failed {detail}`` when it cannot be
                made, ``credential_invalid`` when Windows refuses the
                account's login.
        """
        workspace = self._join(
            data_dir(entry.home, self._os_name, self._join), SIYUAN_WORKSPACE_NAME
        )
        if os.path.isdir(workspace):
            return []
        if self._os_name == "windows":
            failed = self._as_account(instance, _step_make_dir, workspace)
        else:
            result = self._run_as(
                instance.account,
                ["sh", "-c", SIYUAN_POSIX_MKDIR_SHELL, "sh", workspace],
            )
            failed = "" if result.returncode == 0 else _said(result)
        if failed:
            raise ModuleApplyError(
                "apply_failed",
                {"detail": f"could not make {workspace}: {failed}"[:500]},
            )
        return [f"made the workspace of {instance.account}"]

    def record(
        self, parsed: SiyuanConfig, instance: SiyuanInstance, held: dict
    ) -> dict:
        """One instance's record: its ports, its secrets, and the settings it is to have.

        Args:
            parsed: The configuration.
            instance: The instance.
            held: The record held before, with the port the runner took; its
                kernel's port and what was last written are kept.

        Returns:
            The record.
        """
        return {
            "account": instance.account,
            "port": int(held.get("port") or 0),
            "kernel_port": int(held.get("kernel_port") or 0) or self._pick_port(),
            "secret": instance.secret,
            "access_code": instance.access_code,
            "local_name": instance.local_name,
            "cookie_name": instance.cookie_name,
            "gateway_key": instance.gateway_key,
            "gateway_url": parsed.gateway_url,
            "models": list(parsed.models),
            "settings_written": str(held.get("settings_written") or ""),
        }

    def service(
        self, instance: SiyuanInstance, entry: AccountEntry, record: dict
    ) -> AccountService:
        """The kernel as the account, from an environment written from scratch.

        Args:
            instance: The instance.
            entry: Its account; empty for the template.
            record: Its record, whose kernel port the command names.

        Returns:
            The service: its environment root-only, its umask 077.
        """
        kernel_port = int(record.get("kernel_port") or 0)
        data = data_dir(entry.home, self._os_name, self._join) if entry.home else ""
        return AccountService(
            name=self.name,
            title=self.title,
            account=instance.account,
            command=service_command(
                self.kernel_path,
                resources=self.resources_dir,
                data=data,
                kernel_port=kernel_port,
                os_name=self._os_name,
                join=self._join,
            ),
            environment=service_environment(
                instance.access_code,
                data=data,
                kernel_port=kernel_port,
                os_name=self._os_name,
                join=self._join,
            ),
            working_directory="~",
            umask=SIYUAN_UMASK,
            password=instance.password,
            listen_port=kernel_port,
            is_environment_secret=True,
        )

    def on_first_start(self, record: dict) -> str:
        """Write the module's provider into the kernel's settings once the kernel answers.

        The settings are written as the account with the kernel stopped and
        started again after, when the key, the gateway's address or the
        models differ from what the record says was written, and the record
        then keeps what was written.

        Args:
            record: The instance's record.

        Returns:
            Empty once the kernel answers with the settings it is to have.

        Raises:
            OSError: While the kernel does not answer, has made no settings
                yet, or starts again with the settings written.
        """
        account = str(record.get("account", "") or "")
        with socket.create_connection(
            (SIYUAN_UPSTREAM_HOST, int(record.get("kernel_port", 0) or 0)),
            timeout=AGENT_FORWARD_UPSTREAM_TIMEOUT_S,
        ):
            pass
        wanted = settings_digest(
            str(record.get("gateway_key", "") or ""),
            str(record.get("gateway_url", "") or ""),
            [str(name) for name in record.get("models") or []],
        )
        if wanted in (record.get("settings_written"), self._written.get(account)):
            return ""
        try:
            entry = self.machine.lookup_account(account)
        except KeyError:
            return ""
        instance = SiyuanInstance.from_dict(record)
        path = self._join(
            data_dir(entry.home, self._os_name, self._join),
            SIYUAN_WORKSPACE_NAME,
            *SIYUAN_CONF_PARTS,
        )
        if self._read_as(instance, path) is None:
            raise ConnectionError(f"{account}'s kernel has made no settings yet")
        service = self.service(instance, entry, record)
        account_service.stop(service, self.machine)
        try:
            self._write_settings(instance, path, record)
        finally:
            account_service.start(service, self.machine, is_restart=False)
        self._written[account] = wanted
        if self._reapply is not None:
            self._reapply(account, settings_written=wanted)
        raise ConnectionError(f"{account}'s kernel starts again with its settings")

    def admit(self, request, record: dict) -> ForwardDecision:
        """The forwarder's rule: the login path is blocked, a token trades for the kernel's login, the login passes.

        Args:
            request: The request.
            record: The instance's record.

        Returns:
            401 for the kernel's login path whatever the request holds, for
            a token that does not verify and for a request with neither a
            token nor the cookie the browser keeps the login under; a
            redirect to ``/`` setting the kernel's cookie under that name for
            a token that verifies, 502 when the kernel refuses the code or
            does not answer; the relay for a request with the cookie.
        """
        if normal_path(request.path) == normal_path(SIYUAN_LOGIN_PATH):
            return refused()
        name = str(record.get("cookie_name", "") or "")
        if request.token:
            if not record.get("secret") or not request.take_token():
                return refused()
            cookie = self._signed_in(record, request.header("host"))
            if not cookie or not name:
                return answered(502)
            return answered(
                302,
                headers=(
                    ("Location", SIYUAN_HOME_PATH),
                    ("Set-Cookie", name + "=" + cookie.split("=", 1)[1]),
                    ("Cache-Control", "no-store"),
                    ("Referrer-Policy", "no-referrer"),
                ),
            )
        if name and request.cookie_values(name):
            return RELAY
        return refused()

    def connect(self, record: dict) -> socket.socket:
        """A connection to the kernel on loopback.

        Args:
            record: The instance's record.

        Returns:
            The connected socket.

        Raises:
            OSError: When the kernel does not answer.
        """
        return socket.create_connection(
            (SIYUAN_UPSTREAM_HOST, int(record.get("kernel_port", 0) or 0)),
            timeout=AGENT_FORWARD_UPSTREAM_TIMEOUT_S,
        )

    def module_details(self) -> dict:
        """The desktop build installed.

        Returns:
            ``{"version"}``, the version its own description names.
        """
        return {"version": installed_version(self.resources_dir, self._join)}

    @property
    def _os_name(self) -> str:
        return self._platform.os_name

    def _join(self, *parts: str) -> str:
        return (ntpath.join if self._os_name == "windows" else os.path.join)(*parts)

    def _signed_in(self, record: dict, host: str) -> str:
        """The kernel's ``Set-Cookie`` for the access code; empty when it refuses or does not answer."""
        try:
            status, body, headers = self._login(
                int(record.get("kernel_port", 0) or 0),
                host,
                str(record.get("access_code", "") or ""),
            )
        except OSError:
            return ""
        if status != 200 or body.get("code") != 0:
            return ""
        return page_cookie(headers)

    def _write_settings(self, instance: SiyuanInstance, path: str, record: dict):
        """Write the module's provider into the kernel's settings as the account; a failure is a line in the log."""
        text = self._read_as(instance, path)
        try:
            held = json.loads(text or "")
        except ValueError:
            held = None
        if not isinstance(held, dict):
            self._log(f"{self.name}: {instance.account}'s settings do not read")
            return
        settings = with_module_settings(
            held,
            gateway_key=str(record.get("gateway_key", "") or ""),
            gateway_url=str(record.get("gateway_url", "") or ""),
            models=[str(name) for name in record.get("models") or []],
        )
        text = json.dumps(settings, indent=2, ensure_ascii=False) + "\n"
        try:
            if self._os_name == "windows":
                failed = self._as_account(instance, _step_write, path, text)
            else:
                result = self._run_as(
                    instance.account,
                    ["sh", "-c", SIYUAN_POSIX_WRITE_SHELL, "sh", path],
                    stdin=text,
                )
                failed = "" if result.returncode == 0 else _said(result)
        except ModuleApplyError as error:
            failed = f"{error.code} {error.params}"
        if failed:
            self._log(f"{self.name}: {instance.account}'s settings stay: {failed}")
            return
        self._log(f"{self.name}: wrote the gateway into {instance.account}'s settings")

    def _read_as(self, instance: SiyuanInstance, path: str) -> "str | None":
        """One file of the account's, read as the account; None when it cannot be."""
        if self._os_name == "windows":
            try:
                return self._as_account(instance, _step_read, path)
            except ModuleApplyError:
                return None
        try:
            result = self._run_as(instance.account, ["cat", "--", path])
        except ModuleApplyError:
            return None
        return result.stdout if result.returncode == 0 else None

    def _run_as(self, account: str, argv: list, *, stdin: str = ""):
        """Run one command as the account.

        Raises:
            ModuleApplyError: ``apply_failed {detail}`` when it cannot run.
        """
        try:
            return self._platform.run_as_account(
                account, argv, stdin=stdin, timeout_s=SIYUAN_ACCOUNT_STEP_TIMEOUT_S
            )
        except (
            PlatformUnsupportedError,
            OSError,
            subprocess.SubprocessError,
            KeyError,
        ) as error:
            raise ModuleApplyError(
                "apply_failed", {"detail": f"could not run as {account}: {error}"}
            ) from error

    def _as_account(self, instance: SiyuanInstance, step, *arguments):
        """Run one file step on this thread acting as the account, on Windows.

        Raises:
            ModuleApplyError: ``credential_invalid`` when Windows refuses the
                login, ``apply_failed {detail}`` when the thread cannot act
                as the account.
        """
        try:
            return self._platform.as_account(
                instance.account, step, *arguments, password=instance.password
            )
        except (PlatformUnsupportedError, OSError) as error:
            raise ModuleApplyError(
                "apply_failed",
                {"detail": f"could not act as {instance.account}: {error}"},
            ) from error


def _said(result) -> str:
    """What a failed step printed, its last words first."""
    return (result.stderr or result.stdout or "").strip()[-300:] or (
        f"exit {result.returncode}"
    )

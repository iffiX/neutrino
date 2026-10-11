"""A module's instances on Linux: one systemd template unit, one instance per account.

The template ``neutrino_<module>@.service`` runs the program as ``User=%i``,
systemd's name for the instance's account, from a per-account environment
file when the service has one. An instance whose files changed is started
again; an unchanged one is only kept up.

Not pure: writes under ``/etc`` and the state root, and drives systemd.
"""

# PEP 604 unions below are annotations only; this keeps them lazy so the
# agent still imports on the Python 3.9 that older Raspbian ships.
from __future__ import annotations

import contextlib
import os
import subprocess

from neutrino_agent.modules.shared.account_service import (
    remove_account_files,
    unit_name,
    write_account_files,
    write_if_changed,
)
from neutrino_agent.modules.shared.account_service.constants import (
    ACCOUNT_SERVICE_ENVIRONMENT_SUFFIX,
    ACCOUNT_SERVICE_TEMPLATE_ACCOUNT,
    ACCOUNT_SERVICE_UNIT_PREFIX,
    ACCOUNT_SERVICE_UNIT_SUFFIX,
)


def render_unit(template, *, environment_dir: str) -> str:
    """The template unit every instance of one module runs from.

    Args:
        template: The service of the instance whose account is ``%i``.
        environment_dir: Where each account's environment file is; read
            only when the template has an environment.

    Returns:
        The unit file's text.
    """
    lines = [
        "[Unit]",
        f"Description={template.title} for {ACCOUNT_SERVICE_TEMPLATE_ACCOUNT}",
        "After=network-online.target",
        "Wants=network-online.target",
        "",
        "[Service]",
        "Type=simple",
        f"User={ACCOUNT_SERVICE_TEMPLATE_ACCOUNT}",
    ]
    if template.environment:
        path = _environment_path(environment_dir, ACCOUNT_SERVICE_TEMPLATE_ACCOUNT)
        lines.append(f"EnvironmentFile={path}")
    if template.working_directory:
        lines.append(f"WorkingDirectory={template.working_directory}")
    if template.umask:
        lines.append(f"UMask={template.umask}")
    if template.is_output_discarded:
        lines += ["StandardOutput=null", "StandardError=null"]
    lines += [
        f"ExecStart={' '.join(template.command)}",
        "Restart=always",
        "RestartSec=10",
        "",
        "[Install]",
        "WantedBy=multi-user.target",
    ]
    return "\n".join(lines) + "\n"


def render_environment(environment: dict, *, is_quoted: bool) -> str:
    """One account's environment file.

    Args:
        environment: Name to value.
        is_quoted: Whether every value is quoted, with its own quotes and
            backslashes escaped.

    Returns:
        The file's text.
    """
    lines = []
    for name, value in environment.items():
        if is_quoted:
            quoted = str(value).replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{name}="{quoted}"\n')
        else:
            lines.append(f"{name}={value}\n")
    return "".join(lines)


def template_path(name: str, machine) -> str:
    """Where one module's template unit is written."""
    return os.path.join(
        machine.systemd_dir,
        f"{ACCOUNT_SERVICE_UNIT_PREFIX}{name}@{ACCOUNT_SERVICE_UNIT_SUFFIX}",
    )


def define(template, machine) -> bool:
    """Write the template unit and load it when it changed."""
    environment_dir, _mode = _environment_dir(template, machine)
    is_changed = write_if_changed(
        template_path(template.name, machine),
        render_unit(template, environment_dir=environment_dir),
        0o644,
    )
    if is_changed:
        machine.run(["systemctl", "daemon-reload"])
    return is_changed


def write(service, machine) -> bool:
    """Write the account's files and the environment file; whether one changed."""
    entry = machine.lookup_account(service.account)
    is_changed = write_account_files(service, entry, machine)
    if not service.environment:
        return is_changed
    directory, mode = _environment_dir(service, machine)
    os.makedirs(directory, mode=mode, exist_ok=True)
    text = render_environment(
        service.environment, is_quoted=service.is_environment_secret
    )
    return (
        write_if_changed(
            _environment_path(directory, service.account),
            text,
            0o600 if service.is_environment_secret else 0o644,
        )
        or is_changed
    )


def start(service, machine, *, is_restart: bool) -> None:
    """Enable the unit and start it again, or keep it up as it is."""
    unit = unit_name(service.name, service.account)
    if is_restart:
        machine.run(["systemctl", "enable", unit])
        machine.run(["systemctl", "restart", unit])
    else:
        machine.run(["systemctl", "enable", "--now", unit])


def stop(service, machine) -> None:
    """Stop the unit; it stays enabled."""
    unit = unit_name(service.name, service.account)
    machine.run(["systemctl", "stop", unit], is_checked=False)


def remove(service, machine) -> None:
    """Disable the unit and delete the environment file and the account's files."""
    unit = unit_name(service.name, service.account)
    machine.run(["systemctl", "disable", "--now", unit], is_checked=False)
    directory, _mode = _environment_dir(service, machine)
    with contextlib.suppress(OSError):
        os.unlink(_environment_path(directory, service.account))
    remove_account_files(service)


def states(services: list, machine) -> dict:
    """Whether each instance's unit is active."""
    return {
        service.account: {
            "is_running": _is_active(unit_name(service.name, service.account), machine),
            "code": "",
        }
        for service in services
    }


def forget(name: str, machine) -> None:
    """Delete the template unit and tell systemd."""
    with contextlib.suppress(OSError):
        os.unlink(template_path(name, machine))
    machine.run(["systemctl", "daemon-reload"], is_checked=False)


def units(services: list, machine) -> list:
    """Every instance's unit, for the journal."""
    return [unit_name(service.name, service.account) for service in services]


def log_path(name: str, account: str, machine, log_name: str) -> str:
    """No log file: the journal keeps each unit's output."""
    return ""


def _environment_dir(service, machine) -> tuple:
    """Where a service's environment file goes, and the directory's mode."""
    if service.environment_dir:
        return service.environment_dir, 0o755
    return machine.record_dir, 0o700


def _environment_path(directory: str, account: str) -> str:
    return os.path.join(directory, account + ACCOUNT_SERVICE_ENVIRONMENT_SUFFIX)


def _is_active(unit: str, machine) -> bool:
    try:
        result = machine.run(["systemctl", "is-active", unit], is_checked=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.stdout.strip() == "active"

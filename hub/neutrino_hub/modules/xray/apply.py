"""Validating and installing a rendered xray configuration.

The validation step is the reason this is separate from rendering: a config that
xray rejects must never reach the running service, because a failed restart
takes the whole LAN offline.
"""

import json

from neutrino_hub.utils.json_file import write_generated
from neutrino_hub.utils.subprocess_run import CommandError, run

from neutrino_hub.modules.xray.constants import (
    XRAY_BINARY,
    XRAY_CONFIG_PATH,
    XRAY_SERVICE_NAME,
)


class XrayConfigApplier:
    """Writes, validates, and activates the xray configuration."""

    def apply(self, config: dict) -> None:
        """Install a configuration and restart xray.

        Args:
            config: The rendered configuration object.

        Raises:
            CommandError: If xray rejects the configuration or fails to
                restart. The previous config file is left in place when
                validation fails.
        """
        self.write(config)
        self.restart()

    def write(self, config: dict) -> None:
        """Validate a configuration and install it, without restarting.

        Separate from :meth:`apply` because the installer renders every
        generated file before it starts anything: xray's unit points at this
        path, so the file has to exist by the time systemd first runs it.

        Args:
            config: The rendered configuration object.

        Raises:
            CommandError: If xray rejects the configuration. The previous
                config file is left in place in that case.
        """
        self.validate(config)
        write_generated(XRAY_CONFIG_PATH, json.dumps(config, indent=2) + "\n")

    def validate(self, config: dict) -> None:
        """Check a configuration with ``xray run -test``.

        The candidate is written to a temporary path so a broken render cannot
        overwrite the config the running service would reload, and its log
        destinations are stripped first. ``run -test`` builds the whole server,
        loggers included, so validating the config verbatim would create the log
        files — as root, since applying runs as root — and the service, which
        runs as the unprivileged xray user, could then never open them.

        Args:
            config: The rendered configuration object.

        Raises:
            CommandError: If xray reports the configuration invalid.
        """
        candidate = dict(config)
        candidate["log"] = {
            "loglevel": config.get("log", {}).get("loglevel", "warning")
        }
        candidate_path = XRAY_CONFIG_PATH.with_suffix(".candidate.json")
        write_generated(candidate_path, json.dumps(candidate, indent=2) + "\n")
        try:
            run([XRAY_BINARY, "run", "-test", "-config", str(candidate_path)])
        except CommandError as error:
            raise CommandError(f"xray rejected the rendered config: {error}") from error
        finally:
            candidate_path.unlink(missing_ok=True)

    def restart(self) -> None:
        """Restart the xray service.

        Raises:
            CommandError: If systemd reports the restart failed.
        """
        run(["systemctl", "restart", XRAY_SERVICE_NAME])

    def is_running(self) -> bool:
        """Whether the xray service is currently active.

        Returns:
            True when systemd reports the unit active.
        """
        result = run(["systemctl", "is-active", XRAY_SERVICE_NAME], is_checked=False)
        return result.stdout.strip() == "active"

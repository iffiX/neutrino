"""Validating and installing a rendered xray configuration.

The validation step is the reason this is separate from rendering: a config that
xray rejects must never reach the running service, because a failed restart
takes the whole LAN offline.

Validation and a successful restart are two different claims. ``xray run -test``
builds the whole server without binding anything, and the unit is ``Type=simple``,
so ``systemctl restart`` returns before the process has reached its first
listener. A port something else holds passes both and leaves no proxy running.
"""

import json
import time

from neutrino_hub.utils.json_file import write_generated
from neutrino_hub.utils.subprocess_run import CommandError, run

from neutrino_hub.modules.xray.output import failure_of, warnings_of

from neutrino_hub.modules.xray.constants import (
    XRAY_ASSET_DIR,
    XRAY_ASSET_ENV,
    XRAY_BINARY,
    XRAY_CONFIG_PATH,
    XRAY_RESTART_LOG_LINES,
    XRAY_RESTART_SETTLE_S,
    XRAY_SERVICE_NAME,
)


class XrayConfigApplier:
    """Writes, validates, and activates the xray configuration."""

    def apply(self, config: dict) -> None:
        """Install a configuration and restart xray.

        Args:
            config: The rendered configuration object.

        Raises:
            CommandError: If xray rejects the configuration, fails to restart,
                or is gone again a moment later. The previous config file is
                left in place when validation fails.
        """
        self.write(config)
        self.restart()
        self.confirm_running()

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
            CommandError: If xray reports the configuration invalid. The
                message is xray's own reason, not everything it printed on the
                way to it: the banner, the file it read and whatever it wants
                deprecated are on that stream too, and none of them is why it
                said no.
        """
        candidate = dict(config)
        candidate["log"] = {
            "loglevel": config.get("log", {}).get("loglevel", "warning")
        }
        candidate_path = XRAY_CONFIG_PATH.with_suffix(".candidate.json")
        write_generated(candidate_path, json.dumps(candidate, indent=2) + "\n")
        try:
            run(
                [XRAY_BINARY, "run", "-test", "-config", str(candidate_path)],
                environment={XRAY_ASSET_ENV: XRAY_ASSET_DIR},
            )
        except CommandError as error:
            raise CommandError(
                f"xray rejected this configuration: {failure_of(str(error))}"
            ) from error
        finally:
            candidate_path.unlink(missing_ok=True)

    def warnings(self, config: dict) -> list[str]:
        """What xray would complain about in a configuration it accepts.

        Asked separately from validation because they are a different kind of
        answer: a deprecated protocol is worth saying once, beside the node it
        is about, and never inside the message that says an apply failed.

        Args:
            config: The rendered configuration object.

        Returns:
            One line per warning, empty when xray had none or could not be
            run at all — this reports, so it never raises.
        """
        candidate = dict(config)
        candidate["log"] = {
            "loglevel": config.get("log", {}).get("loglevel", "warning")
        }
        candidate_path = XRAY_CONFIG_PATH.with_suffix(".warnings.json")
        try:
            write_generated(candidate_path, json.dumps(candidate, indent=2) + "\n")
            result = run(
                [XRAY_BINARY, "run", "-test", "-config", str(candidate_path)],
                environment={XRAY_ASSET_ENV: XRAY_ASSET_DIR},
                is_checked=False,
            )
        except (CommandError, OSError):
            return []
        finally:
            candidate_path.unlink(missing_ok=True)
        return warnings_of(result.stdout + result.stderr)

    def restart(self) -> None:
        """Restart the xray service.

        Raises:
            CommandError: If systemd reports the restart failed.
        """
        run(["systemctl", "restart", XRAY_SERVICE_NAME])

    def confirm_running(self, *, settle_s: float = XRAY_RESTART_SETTLE_S) -> None:
        """Check the service is still up a moment after being restarted.

        Args:
            settle_s: How long the process is given to reach its listeners.

        Raises:
            CommandError: If the unit is not active, carrying the last lines of
                its journal, which is where the port it could not take is named.
        """
        time.sleep(settle_s)
        if self.is_running():
            return
        journal = run(
            [
                "journalctl",
                "-u",
                XRAY_SERVICE_NAME,
                "-n",
                str(XRAY_RESTART_LOG_LINES),
                "--no-pager",
                "-o",
                "cat",
            ],
            is_checked=False,
        )
        reason = " ".join(journal.stdout.split()) or "no reason in its journal"
        raise CommandError(f"xray stopped again after the restart: {reason}")

    def is_running(self) -> bool:
        """Whether the xray service is currently active.

        Returns:
            True when systemd reports the unit active.
        """
        result = run(["systemctl", "is-active", XRAY_SERVICE_NAME], is_checked=False)
        return result.stdout.strip() == "active"

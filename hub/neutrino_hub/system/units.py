"""Writing the hub's own systemd units.

The templates ship inside the package and name two things the installation
decides: the interpreter to run, and the checkout they run from. Both are
filled in here, so an upgraded package's units land the next time anything
makes the box true rather than only on a first setup.
"""

from neutrino_hub.system.constants import SYSTEM_SYSTEMD_DIR
from neutrino_hub.system.installation import checkout_root, is_packaged, venv_python
from neutrino_hub.system.systemd_ctl import SystemdServiceController
from neutrino_hub.utils.constants import UTILS_DATA_DIR

# --- config ---
# The units the hub owns, template name to installed name. The proxy core is
# among them: it travels in the package, so its unit is the hub's own rather
# than a drop-in over one a vendor's script installed.
SYSTEM_UNIT_TEMPLATES = {
    "neutrino_hub_router.service": "neutrino_hub_router.service",
    "neutrino_hub_web.service": "neutrino_hub_web.service",
    # Templated by interface: one access point per radio given the LAN role.
    "neutrino_hub_hostapd@.service": "neutrino_hub_hostapd@.service",
    "neutrino_hub_xray.service": "neutrino_hub_xray.service",
}
# What a checkout's templates say, and what a package has instead.
SYSTEM_UNIT_CHECKOUT_LINES = (
    "WorkingDirectory=@REPO_ROOT@",
    "Environment=PYTHONPATH=@REPO_ROOT@",
)
SYSTEM_UNIT_DOCUMENTATION = (
    "Documentation=file://@REPO_ROOT@/docs/standard/misc/config.md"
)
SYSTEM_UNIT_DOCUMENTATION_URL = "Documentation=https://github.com/iffiX/neutrino"


class SystemdUnitInstaller:
    """Puts the hub's units where systemd reads them."""

    def install(self) -> list:
        """Write every unit whose content differs from what is installed.

        Returns:
            The units written, empty when they were all already current.
        """
        # The units must run the environment's interpreter, not whichever
        # python launched this: the panel's dependencies live only there.
        python_path = str(venv_python())
        written = []
        for template_name, unit_name in SYSTEM_UNIT_TEMPLATES.items():
            template = (UTILS_DATA_DIR / "services" / template_name).read_text(
                encoding="utf-8"
            )
            rendered = self.render(template, python_path)
            destination = SYSTEM_SYSTEMD_DIR / unit_name
            if (
                destination.is_file()
                and destination.read_text(encoding="utf-8") == rendered
            ):
                continue
            destination.write_text(rendered, encoding="utf-8")
            written.append(unit_name)
        if written:
            SystemdServiceController().daemon_reload()
        return written

    def render(self, template: str, python_path: str) -> str:
        """One unit template with this installation's paths in it.

        A checkout runs the hub from the tree it sits in, so its units say
        where that is. A package carries the hub inside its own environment,
        where those lines would name a directory inside the environment
        itself: they are dropped rather than pointed somewhere.

        Args:
            template: The unit template's text.
            python_path: The interpreter the unit must run.

        Returns:
            The unit to write.
        """
        if not is_packaged():
            return template.replace("@REPO_ROOT@", str(checkout_root())).replace(
                "@PYTHON@", python_path
            )
        kept = [
            line
            for line in template.splitlines()
            if not line.startswith(SYSTEM_UNIT_CHECKOUT_LINES)
        ]
        return (
            "\n".join(kept)
            .replace(SYSTEM_UNIT_DOCUMENTATION, SYSTEM_UNIT_DOCUMENTATION_URL)
            .replace("@PYTHON@", python_path)
            + "\n"
        )

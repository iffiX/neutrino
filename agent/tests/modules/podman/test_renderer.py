"""The rendered container files, checked for what systemd will read, and the
root script that carries them into a Podman machine, run with ``sh`` against
a temporary root."""

import base64
import os
import re
import subprocess
from pathlib import Path

import pytest

from neutrino_agent.modules.podman.config import PodmanConfig, PodmanContainer
from neutrino_agent.modules.podman.constants import PODMAN_GENERATED_MARKER
from neutrino_agent.modules.podman.renderer import (
    PodmanMachineScriptRenderer,
    PodmanQuadletRenderer,
    PodmanRegistriesRenderer,
    PodmanUnitRenderer,
    machine_boot_unit,
    machine_control_script,
    machine_journal_script,
    machine_stop_script,
    qualified_image,
)


def render(containers: list) -> dict:
    config = PodmanConfig.from_dict({"containers": containers})
    config.validate()
    return PodmanQuadletRenderer(config=config).render()


FULL = {
    "name": "webdav",
    "image": "docker.io/library/nginx:1",
    "ports": ["8081:80"],
    "volumes": ["/srv/share:/usr/share/nginx/html"],
    "environment": ["TZ=Asia/Shanghai"],
    "is_autostart": True,
}


def test_one_file_per_container_named_for_it():
    assert set(render([FULL, {"name": "redis", "image": "r"}])) == {
        "webdav.container",
        "redis.container",
    }


def test_every_declared_knob_lands_in_the_unit():
    text = render([FULL])["webdav.container"]

    assert "ContainerName=webdav" in text
    assert "Image=docker.io/library/nginx:1" in text
    assert "PublishPort=8081:80" in text
    assert "Volume=/srv/share:/usr/share/nginx/html" in text
    assert "Environment=TZ=Asia/Shanghai" in text
    assert "WantedBy=multi-user.target" in text
    assert "TimeoutStartSec=900" in text


def test_no_autostart_means_no_install_section():
    text = render([{**FULL, "is_autostart": False}])["webdav.container"]

    assert "[Install]" not in text


def test_every_file_carries_the_marker_that_makes_removal_safe():
    for text in render([FULL, {"name": "redis", "image": "r"}]).values():
        assert text.startswith(PODMAN_GENERATED_MARKER)


def test_short_image_names_are_qualified_in_the_unit():
    assert qualified_image("python:3.12") == "docker.io/library/python:3.12"
    assert qualified_image("iffi/tool:1") == "docker.io/iffi/tool:1"
    assert qualified_image("ghcr.io/owner/thing:2") == "ghcr.io/owner/thing:2"
    assert qualified_image("localhost:5000/x") == "localhost:5000/x"


def test_mirrors_render_in_order_and_none_renders_nothing():
    config = PodmanConfig.from_dict(
        {
            "containers": [],
            "mirrors": ["mirror.ccs.tencentyun.com", "registry.docker-cn.com"],
        }
    )
    text = PodmanRegistriesRenderer(config=config).render()

    assert 'prefix = "docker.io"' in text
    assert text.index("mirror.ccs.tencentyun.com") < text.index(
        "registry.docker-cn.com"
    )
    assert PodmanRegistriesRenderer(config=PodmanConfig()).render() == ""


def test_a_command_overrides_the_images_own_and_absent_stays_absent():
    with_command = render(
        [{"name": "py", "image": "python:3.12", "command": "python3 -m http.server"}]
    )["py.container"]
    without = render([{"name": "py", "image": "python:3.12"}])["py.container"]

    assert "Exec=python3 -m http.server" in with_command
    assert "Exec=" not in without


def unit(container: PodmanContainer) -> str:
    config = PodmanConfig(containers=[container], mirrors=[])
    return PodmanUnitRenderer(config=config).render()[f"{container.name}.service"]


def exec_start(container: PodmanContainer) -> str:
    for line in unit(container).splitlines():
        if line.startswith("ExecStart="):
            return line
    raise AssertionError("the unit has no ExecStart")


def test_a_unit_is_named_the_same_as_its_quadlet_file_would_be():
    container = PodmanContainer(name="redis", image="redis:7")
    config = PodmanConfig(containers=[container], mirrors=[])
    assert set(PodmanUnitRenderer(config=config).render()) == {"redis.service"}
    assert set(PodmanQuadletRenderer(config=config).render()) == {"redis.container"}


def test_the_six_container_properties_reach_the_command_line():
    line = exec_start(
        PodmanContainer(
            name="app",
            image="nginx",
            ports=["8080:80", "5353:53/udp"],
            volumes=["/srv/data:/data", "cache:/cache"],
            environment=["TZ=UTC"],
        )
    )
    assert "--name app" in line
    assert "-p 8080:80" in line and "-p 5353:53/udp" in line
    assert "-v /srv/data:/data" in line and "-v cache:/cache" in line
    assert "-e TZ=UTC" in line
    assert line.endswith("docker.io/library/nginx")


def test_an_environment_value_with_spaces_stays_one_argument():
    line = exec_start(
        PodmanContainer(
            name="app", image="nginx", environment=["JAVA_OPTS=-Xmx1g -Xms512m"]
        )
    )
    assert '-e "JAVA_OPTS=-Xmx1g -Xms512m"' in line


def test_a_command_is_passed_through_for_systemd_to_split():
    line = exec_start(
        PodmanContainer(name="app", image="python:3.12", command='sh -c "sleep 3600"')
    )
    assert line.endswith('docker.io/library/python:3.12 sh -c "sleep 3600"')


def test_a_leftover_container_does_not_block_the_next_start():
    text = unit(PodmanContainer(name="app", image="nginx"))
    assert "ExecStartPre=-/usr/bin/podman rm -f app" in text
    assert "ExecStop=/usr/bin/podman stop -t 10 app" in text


def test_only_an_autostart_container_is_wanted_by_the_boot_target():
    assert "WantedBy=multi-user.target" in unit(
        PodmanContainer(name="app", image="nginx", is_autostart=True)
    )
    assert "WantedBy=" not in unit(
        PodmanContainer(name="app", image="nginx", is_autostart=False)
    )
    assert unit(PodmanContainer(name="app", image="nginx")).startswith(
        PODMAN_GENERATED_MARKER
    )


def publishes(container: dict) -> list:
    text = render([container])[f"{container['name']}.container"]
    return [line for line in text.splitlines() if line.startswith("PublishPort=")]


def test_no_services_and_every_port_auto_render_the_same_file():
    plain = {"name": "app", "image": "nginx", "ports": ["8080:80", "5353:53/udp"]}
    auto = {
        **plain,
        "services": [{"port": 8080, "kind": "auto"}, {"port": 5353, "kind": "auto"}],
    }

    assert render([plain]) == render([auto])
    assert publishes(plain) == ["PublishPort=8080:80", "PublishPort=5353:53/udp"]


def test_a_web_port_publishes_tcp():
    container = {
        "name": "app",
        "image": "nginx",
        "ports": ["8443:443/udp"],
        "services": [{"port": 8443, "kind": "web", "scheme": "https"}],
    }

    assert publishes(container) == ["PublishPort=8443:443"]


def test_a_port_port_publishes_each_checked_protocol_once():
    container = {
        "name": "dns",
        "image": "coredns",
        "ports": ["53:53", "53:53/udp", "9000:9000/udp"],
        "services": [
            {"port": 53, "kind": "port", "protocols": ["udp", "tcp"]},
            {"port": 9000, "kind": "port", "protocols": ["tcp"]},
        ],
    }

    assert publishes(container) == [
        "PublishPort=53:53",
        "PublishPort=53:53/udp",
        "PublishPort=9000:9000",
    ]


def test_a_checked_udp_reaches_the_command_line_of_an_old_podman():
    line = exec_start(
        PodmanContainer.from_dict(
            {
                "name": "dns",
                "image": "coredns",
                "ports": ["53:53"],
                "services": [{"port": 53, "kind": "port", "protocols": ["tcp", "udp"]}],
            }
        )
    )

    assert "-p 53:53 -p 53:53/udp" in line


# --- the Podman machine on Windows and macOS ---

GOLDEN = Path(__file__).parent / "golden"

# One file's text as the root script carries it; the golden holds a
# placeholder in its place.
ENCODED_PATTERN = re.compile(r"'([A-Za-z0-9+/]{40,}={0,2})'")

MACHINE_CONTAINERS = [
    {
        "name": "web",
        "image": "nginx",
        "ports": ["8080:80", "5353:53"],
        "volumes": ["C:\\www:/usr/share/nginx/html:ro", "webdata:/data"],
        "services": [{"port": 5353, "kind": "port", "protocols": ["tcp"]}],
    },
    {"name": "batch", "image": "alpine", "command": "sleep 60", "is_autostart": False},
]


def machine_config(containers=None, mirrors=()) -> PodmanConfig:
    config = PodmanConfig.from_dict(
        {
            "containers": MACHINE_CONTAINERS if containers is None else containers,
            "mirrors": list(mirrors),
            "machine": {"account": "lab", "password": "pw"},
        }
    )
    config.validate(os_name="windows")
    return config


def test_a_machine_file_has_the_cgroups_line_and_the_folder_as_wsl_mounts_it():
    config = machine_config()

    text = PodmanQuadletRenderer(config=config, machine_os_name="windows").render()[
        "web.container"
    ]

    assert text.splitlines()[6:14] == [
        "[Container]",
        "ContainerName=web",
        "Image=docker.io/library/nginx",
        "PublishPort=8080:80",
        "PublishPort=5353:53",
        "Volume=/mnt/c/www:/usr/share/nginx/html:ro",
        "Volume=webdata:/data",
        "CgroupsMode=enabled",
    ]


def test_a_mac_machine_file_keeps_the_folder_and_adds_the_cgroups_line():
    config = PodmanConfig.from_dict(
        {
            "containers": [
                {"name": "site", "image": "nginx", "volumes": ["/Users/me:/s"]}
            ]
        }
    )

    text = PodmanQuadletRenderer(config=config, machine_os_name="darwin").render()[
        "site.container"
    ]

    assert "Volume=/Users/me:/s\nCgroupsMode=enabled\n" in text


def test_the_linux_file_has_no_cgroups_line_and_is_byte_for_byte_as_before():
    linux = PodmanQuadletRenderer(config=machine_config()).render()

    assert "CgroupsMode" not in "".join(linux.values())
    assert linux["batch.container"] == (
        f"{PODMAN_GENERATED_MARKER}\n"
        "\n"
        "[Unit]\n"
        "Description=batch container\n"
        "After=network-online.target\n"
        "\n"
        "[Container]\n"
        "ContainerName=batch\n"
        "Image=docker.io/library/alpine\n"
        "Exec=sleep 60\n"
        "\n"
        "[Service]\n"
        "TimeoutStartSec=900\n"
        "Restart=on-failure\n"
    )


def test_the_root_script_renders_the_golden_text_around_each_files_base64():
    config = machine_config(mirrors=["mirror.example"])
    script = PodmanMachineScriptRenderer(config=config, os_name="windows").render()
    payloads = ENCODED_PATTERN.findall(script)

    assert ENCODED_PATTERN.sub("'BASE64'", script) == (
        GOLDEN / "machine_script.sh"
    ).read_text(encoding="utf-8")
    rendered = PodmanQuadletRenderer(config=config, machine_os_name="windows").render()
    assert [base64.b64decode(payload).decode() for payload in payloads] == [
        rendered["web.container"],
        rendered["batch.container"],
        PodmanRegistriesRenderer(config=config).render(),
    ]


def test_the_mac_script_writes_where_linux_has_the_files_with_the_cgroups_line(
    tmp_path,
):
    shell = MachineShell(tmp_path, "darwin")
    config = machine_config()

    done, _calls = shell.run(config)

    assert done.returncode == 0, done.stderr
    assert shell.quadlet == shell.root / "etc/containers/systemd"
    text = (shell.quadlet / "web.container").read_text()
    assert text == (
        PodmanQuadletRenderer(config=config, machine_os_name="darwin").render()[
            "web.container"
        ]
    )
    assert "\nCgroupsMode=enabled\n" in text
    assert not (shell.root / "usr").exists()


# A systemctl that records each call, reads a unit active when ACTIVE names
# it, and refuses a restart of a unit REFUSED names.
SYSTEMCTL_STUB = """#!/bin/sh
echo "$*" >> "$SYSTEMCTL_LOG"
if [ "$1" = is-active ]; then
    case " $ACTIVE " in *" $3 "*) exit 0 ;; esac
    exit 3
fi
if [ "$1" = restart ]; then
    case " $REFUSED " in *" $2 "*) echo "Job for $2 failed." >&2; exit 1 ;; esac
fi
exit 0
"""


class MachineShell:
    """The root script run with ``sh`` against a temporary root, systemctl stubbed."""

    def __init__(self, tmp_path, os_name="windows"):
        self.os_name = os_name
        self.root = tmp_path / "machine"
        self.quadlet = self.root / (
            "usr/share/containers/systemd"
            if os_name == "windows"
            else "etc/containers/systemd"
        )
        self.mirrors = (
            self.root / "etc/containers/registries.conf.d/99_neutrino_mirrors.conf"
        )
        self.log = tmp_path / "systemctl.log"
        stubs = tmp_path / "bin"
        stubs.mkdir()
        stub = stubs / "systemctl"
        stub.write_text(SYSTEMCTL_STUB)
        stub.chmod(0o755)
        self.path = f"{stubs}{os.pathsep}{os.environ.get('PATH', '')}"

    def run(self, config: PodmanConfig, *, active="", refused="") -> tuple:
        self.log.write_text("")
        script = PodmanMachineScriptRenderer(
            config=config, os_name=self.os_name, root=str(self.root)
        ).render()
        done = subprocess.run(
            ["sh", "-s"],
            input=script,
            capture_output=True,
            text=True,
            env={
                "PATH": self.path,
                "SYSTEMCTL_LOG": str(self.log),
                "ACTIVE": active,
                "REFUSED": refused,
            },
            timeout=60,
        )
        return done, self.log.read_text().splitlines()


def changed_lines(done) -> list:
    return [line for line in done.stdout.splitlines() if line.startswith("changed: ")]


def test_the_script_writes_every_file_and_restarts_what_starts_at_boot(tmp_path):
    shell = MachineShell(tmp_path)
    config = machine_config(mirrors=["mirror.example"])

    done, calls = shell.run(config)

    assert done.returncode == 0, done.stderr
    rendered = PodmanQuadletRenderer(config=config, machine_os_name="windows").render()
    assert (shell.quadlet / "web.container").read_text() == rendered["web.container"]
    assert (shell.quadlet / "batch.container").read_text() == rendered[
        "batch.container"
    ]
    assert shell.mirrors.read_text() == PodmanRegistriesRenderer(config=config).render()
    assert changed_lines(done) == [
        f"changed: {shell.quadlet}/web.container",
        f"changed: {shell.quadlet}/batch.container",
        f"changed: {shell.mirrors}",
    ]
    assert calls == [
        "daemon-reload",
        "is-active --quiet batch.service",
        "restart web.service",
    ]
    assert not list(shell.quadlet.glob("*.new"))


def test_an_unchanged_configuration_changes_nothing_and_restarts_nothing(tmp_path):
    shell = MachineShell(tmp_path)
    config = machine_config(mirrors=["mirror.example"])
    shell.run(config)

    done, calls = shell.run(config, active="web.service batch.service")

    assert done.returncode == 0, done.stderr
    assert changed_lines(done) == []
    assert calls == ["daemon-reload"]


def test_a_changed_container_that_runs_restarts_though_not_started_at_boot(tmp_path):
    shell = MachineShell(tmp_path)
    shell.run(machine_config())
    changed = [MACHINE_CONTAINERS[0], dict(MACHINE_CONTAINERS[1], command="sleep 9")]

    done, calls = shell.run(machine_config(changed), active="batch.service")

    assert changed_lines(done) == [f"changed: {shell.quadlet}/batch.container"]
    assert calls == [
        "daemon-reload",
        "is-active --quiet batch.service",
        "restart batch.service",
    ]


def test_stale_generated_files_go_and_a_persons_own_file_stays(tmp_path):
    shell = MachineShell(tmp_path)
    shell.quadlet.mkdir(parents=True)
    (shell.quadlet / "old.container").write_text(
        f"{PODMAN_GENERATED_MARKER}\n[Container]\n"
    )
    (shell.quadlet / "mine.container").write_text("[Container]\nImage=mine\n")
    shell.mirrors.parent.mkdir(parents=True)
    shell.mirrors.write_text(f"{PODMAN_GENERATED_MARKER}\n")

    done, calls = shell.run(machine_config())

    assert not (shell.quadlet / "old.container").exists()
    assert (shell.quadlet / "mine.container").read_text() == "[Container]\nImage=mine\n"
    assert not shell.mirrors.exists()
    assert f"changed: -{shell.quadlet}/old.container" in changed_lines(done)
    assert f"changed: -{shell.mirrors}" in changed_lines(done)
    assert "stop old.service" in calls
    assert "stop mine.service" not in calls


def test_an_empty_configuration_takes_every_generated_file_away(tmp_path):
    shell = MachineShell(tmp_path)
    shell.run(machine_config(mirrors=["mirror.example"]))

    done, calls = shell.run(PodmanConfig())

    assert done.returncode == 0, done.stderr
    assert list(shell.quadlet.iterdir()) == []
    assert not shell.mirrors.exists()
    assert calls == ["stop batch.service", "stop web.service", "daemon-reload"]


def test_a_refused_restart_fails_the_script_with_systemds_words(tmp_path):
    shell = MachineShell(tmp_path)

    done, _calls = shell.run(machine_config(), refused="web.service")

    assert done.returncode == 1
    assert "Job for web.service failed." in done.stderr


def test_the_verbs_scripts_name_the_containers_unit():
    assert machine_control_script("web", "restart") == "systemctl restart web.service\n"
    assert machine_journal_script("web", 200) == (
        "journalctl -u web.service -n 200 --no-pager --output short-iso\n"
    )
    with pytest.raises(ValueError):
        machine_control_script("web", "kill")


@pytest.mark.parametrize("os_name", ["windows", "darwin"])
def test_the_stop_script_stops_each_generated_container_and_keeps_its_file(
    tmp_path, os_name
):
    shell = MachineShell(tmp_path, os_name)
    shell.run(machine_config())
    (shell.quadlet / "mine.container").write_text("[Container]\n")
    shell.log.write_text("")

    subprocess.run(
        ["sh", "-s"],
        input=machine_stop_script(os_name=os_name, root=str(shell.root)),
        text=True,
        env={"PATH": shell.path, "SYSTEMCTL_LOG": str(shell.log)},
        check=True,
        timeout=60,
    )

    assert shell.log.read_text().splitlines() == [
        "stop batch.service",
        "stop web.service",
    ]
    assert (shell.quadlet / "web.container").exists()


# --- the boot unit, where the machine mounts the computer's /etc/containers ---

BOOT_UNIT = "etc/systemd/system/neutrino_containers.service"
BOOT_LINK = "etc/systemd/system/multi-user.target.wants/neutrino_containers.service"


def mounted_machine(tmp_path) -> "MachineShell":
    """A macOS machine whose own unit mounts the computer's folder on /etc/containers."""
    shell = MachineShell(tmp_path, "darwin")
    mount_unit = shell.root / "etc/systemd/system/etc-containers.mount"
    mount_unit.parent.mkdir(parents=True)
    mount_unit.write_text("[Mount]\nWhere=/etc/containers\n")
    return shell


def test_the_boot_unit_reloads_systemd_and_starts_multi_user_after_the_mount():
    unit = machine_boot_unit()

    assert unit.startswith(PODMAN_GENERATED_MARKER + "\n")
    assert "RequiresMountsFor=/etc/containers\n" in unit
    assert unit.index("ExecStart=/usr/bin/systemctl daemon-reload\n") < unit.index(
        "ExecStart=/usr/bin/systemctl start --no-block multi-user.target\n"
    )
    assert unit.endswith("[Install]\nWantedBy=multi-user.target\n")


def test_a_mounted_machine_gets_the_boot_unit_turned_on_once(tmp_path):
    shell = mounted_machine(tmp_path)

    done, _calls = shell.run(machine_config())
    again, _calls = shell.run(machine_config())

    assert done.returncode == 0, done.stderr
    assert (shell.root / BOOT_UNIT).read_text() == machine_boot_unit()
    assert os.readlink(shell.root / BOOT_LINK) == "../neutrino_containers.service"
    assert changed_lines(done)[-2:] == [
        f"changed: {shell.root / BOOT_UNIT}",
        f"changed: {shell.root / BOOT_LINK}",
    ]
    assert again.returncode == 0, again.stderr
    assert changed_lines(again) == []


def test_a_machine_without_the_mount_has_no_boot_unit_and_loses_a_stale_one(
    tmp_path,
):
    shell = MachineShell(tmp_path, "darwin")
    stale = shell.root / BOOT_UNIT
    stale.parent.mkdir(parents=True)
    stale.write_text(machine_boot_unit())

    done, _calls = shell.run(machine_config())

    assert done.returncode == 0, done.stderr
    assert not stale.exists()
    assert changed_lines(done)[-1] == f"changed: -{stale}"


def test_no_containers_take_the_boot_unit_and_its_link_away(tmp_path):
    shell = mounted_machine(tmp_path)
    shell.run(machine_config())

    done, _calls = shell.run(PodmanConfig())

    assert done.returncode == 0, done.stderr
    assert not (shell.root / BOOT_UNIT).exists()
    assert not os.path.lexists(shell.root / BOOT_LINK)


def test_a_person_s_unit_of_the_same_name_is_left(tmp_path):
    shell = MachineShell(tmp_path, "darwin")
    mine = shell.root / BOOT_UNIT
    mine.parent.mkdir(parents=True)
    mine.write_text("[Unit]\nDescription=mine\n")

    done, _calls = shell.run(machine_config())

    assert done.returncode == 0, done.stderr
    assert mine.read_text() == "[Unit]\nDescription=mine\n"


def test_the_windows_script_has_no_boot_unit():
    script = PodmanMachineScriptRenderer(
        config=machine_config(), os_name="windows"
    ).render()

    assert "neutrino_containers" not in script

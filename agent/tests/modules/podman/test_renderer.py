"""The rendered container units and environment files, checked for what
systemd and Podman will read, and the root script that carries them into a
Podman machine, run with ``sh`` against a temporary root."""

import base64
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from neutrino_agent.modules.podman.config import PodmanConfig, PodmanContainer
from neutrino_agent.modules.podman.constants import PODMAN_GENERATED_MARKER
from neutrino_agent.modules.podman.renderer import (
    PodmanMachineScriptRenderer,
    PodmanRegistriesRenderer,
    PodmanRenderContext,
    PodmanUnitRenderer,
    machine_control_script,
    machine_drop_script,
    machine_journal_script,
    machine_stop_script,
    qualified_image,
    source_neutral,
)

ENV_DIR = "/var/lib/neutrino/agent/podman/env"


def renderer_of(containers: list, **kwargs) -> PodmanUnitRenderer:
    config = PodmanConfig.from_dict({"containers": containers})
    config.validate()
    return PodmanUnitRenderer(config=config, **kwargs)


def render(containers: list) -> dict:
    return renderer_of(containers).render()


def environments(containers: list) -> dict:
    return renderer_of(containers).environment_files()


FULL = {
    "name": "webdav",
    "image": "docker.io/library/nginx:1",
    "ports": ["8081:80"],
    "volumes": ["/srv/share:/usr/share/nginx/html"],
    "environment": ["TZ=Asia/Shanghai"],
    "is_autostart": True,
}


def exec_start(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("ExecStart="):
            return line
    raise AssertionError("the unit has no ExecStart")


def test_one_unit_and_one_environment_file_per_container_named_for_it():
    containers = [FULL, {"name": "redis", "image": "r"}]

    assert set(render(containers)) == {"webdav.service", "redis.service"}
    assert set(environments(containers)) == {"webdav.env", "redis.env"}


def test_the_unit_carries_podman_s_lifecycle_settings_and_no_environment_value():
    assert render([FULL])["webdav.service"].splitlines() == [
        PODMAN_GENERATED_MARKER,
        "",
        "[Unit]",
        "Description=webdav container",
        "Wants=network-online.target",
        "After=network-online.target",
        "RequiresMountsFor=/srv/share",
        "",
        "[Service]",
        "Environment=PODMAN_SYSTEMD_UNIT=%n",
        "Type=notify",
        "NotifyAccess=all",
        "Delegate=yes",
        "KillMode=mixed",
        "Restart=on-failure",
        "SuccessExitStatus=143",
        "TimeoutStartSec=900",
        "TimeoutStopSec=70",
        "ExecStartPre=-/bin/rm -f %t/%N.cid",
        "ExecStart=/usr/bin/podman run --cidfile=%t/%N.cid --cgroups=split"
        " --sdnotify=conmon -d --replace --rm --name webdav -p 8081:80"
        " -v /srv/share:/usr/share/nginx/html"
        f" --env-file {ENV_DIR}/webdav.env docker.io/library/nginx:1",
        "ExecStop=/usr/bin/podman stop --ignore -t 10 --cidfile=%t/%N.cid",
        "ExecStopPost=-/usr/bin/podman rm -f --ignore --cidfile=%t/%N.cid",
        "",
        "[Install]",
        "WantedBy=multi-user.target",
    ]


def test_the_environment_is_in_its_file_as_written_and_nowhere_in_the_unit():
    container = {
        "name": "app",
        "image": "nginx",
        "environment": ["TZ=UTC", "JAVA_OPTS=-Xmx1g -Xms512m", 'PASS=p%a$s"w #1'],
    }

    unit = render([container])["app.service"]

    assert environments([container])["app.env"] == (
        f"{PODMAN_GENERATED_MARKER}\n"
        "TZ=UTC\n"
        "JAVA_OPTS=-Xmx1g -Xms512m\n"
        'PASS=p%a$s"w #1\n'
    )
    assert " -e " not in exec_start(unit)
    for value in ("UTC", "Xmx1g", "p%a"):
        assert value not in unit


def test_a_container_with_no_environment_has_a_file_with_the_marker_alone():
    assert environments([{"name": "redis", "image": "r"}]) == {
        "redis.env": PODMAN_GENERATED_MARKER + "\n"
    }


def test_no_autostart_means_no_install_section():
    text = render([{**FULL, "is_autostart": False}])["webdav.service"]

    assert "[Install]" not in text
    assert "WantedBy=" not in text


def test_every_file_carries_the_marker_that_makes_removal_safe():
    containers = [FULL, {"name": "redis", "image": "r"}]
    for text in [*render(containers).values(), *environments(containers).values()]:
        assert text.startswith(PODMAN_GENERATED_MARKER + "\n")


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


def test_a_command_is_passed_through_for_systemd_to_split():
    with_command = render(
        [{"name": "py", "image": "python:3.12", "command": 'sh -c "sleep 3600"'}]
    )["py.service"]
    without = render([{"name": "py", "image": "python:3.12"}])["py.service"]

    assert exec_start(with_command).endswith(
        'docker.io/library/python:3.12 sh -c "sleep 3600"'
    )
    assert exec_start(without).endswith("docker.io/library/python:3.12")


def test_the_container_s_properties_reach_the_command_line():
    line = exec_start(
        render(
            [
                {
                    "name": "app",
                    "image": "nginx",
                    "ports": ["8080:80", "5353:53/udp"],
                    "volumes": ["/srv/data:/data", "cache:/cache"],
                }
            ]
        )["app.service"]
    )

    assert "--name app" in line
    assert "-p 8080:80 -p 5353:53/udp" in line
    assert "-v /srv/data:/data -v cache:/cache" in line
    assert line.endswith(f"--env-file {ENV_DIR}/app.env docker.io/library/nginx")


def test_each_host_folder_a_volume_binds_is_a_mount_the_unit_requires():
    text = render(
        [
            {
                "name": "app",
                "image": "nginx",
                "volumes": ["/srv/data:/data:ro", "cache:/cache", "/srv/my files:/f"],
            }
        ]
    )["app.service"]

    assert [line for line in text.splitlines() if "RequiresMountsFor" in line] == [
        "RequiresMountsFor=/srv/data",
        'RequiresMountsFor="/srv/my files"',
    ]
    assert '-v "/srv/my files:/f"' in exec_start(text)


def test_a_volume_s_specifiers_and_variables_reach_podman_as_written():
    text = render([{"name": "app", "image": "nginx", "volumes": ["/srv/a%b$c:/d"]}])[
        "app.service"
    ]

    assert "-v /srv/a%%b$$c:/d" in exec_start(text)
    assert "RequiresMountsFor=/srv/a%%b$c" in text


def publishes(container: dict) -> list:
    words = exec_start(render([container])[f"{container['name']}.service"]).split()
    return [words[index + 1] for index, word in enumerate(words) if word == "-p"]


def test_no_services_and_every_port_auto_render_the_same_files():
    plain = {"name": "app", "image": "nginx", "ports": ["8080:80", "5353:53/udp"]}
    auto = {
        **plain,
        "services": [{"port": 8080, "kind": "auto"}, {"port": 5353, "kind": "auto"}],
    }

    assert render([plain]) == render([auto])
    assert environments([plain]) == environments([auto])
    assert publishes(plain) == ["8080:80", "5353:53/udp"]


def test_a_web_port_publishes_tcp():
    container = {
        "name": "app",
        "image": "nginx",
        "ports": ["8443:443/udp"],
        "services": [{"port": 8443, "kind": "web", "scheme": "https"}],
    }

    assert publishes(container) == ["8443:443"]


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

    assert publishes(container) == ["53:53", "53:53/udp", "9000:9000"]


def test_a_unit_made_from_a_container_object_is_the_same():
    container = PodmanContainer(name="redis", image="redis:7")
    config = PodmanConfig(containers=[container], mirrors=[])

    assert PodmanUnitRenderer(config=config).render() == render(
        [{"name": "redis", "image": "redis:7"}]
    )


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
        "environment": ["TZ=UTC"],
        "services": [{"port": 5353, "kind": "port", "protocols": ["tcp"]}],
    },
    {"name": "batch", "image": "alpine", "command": "sleep 60", "is_autostart": False},
]


def machine_config(containers=None, mirrors=()) -> PodmanConfig:
    config = PodmanConfig.from_dict(
        {
            "containers": MACHINE_CONTAINERS if containers is None else containers,
            "mirrors": list(mirrors),
            "machine": {"account": "lab", "password": "pw", "disk_gib": 100},
        }
    )
    config.validate(os_name="windows")
    return config


def machine_renderer(config, os_name="windows", context=None) -> PodmanUnitRenderer:
    return PodmanUnitRenderer(config=config, machine_os_name=os_name, context=context)


def test_a_machine_unit_runs_cgroups_enabled_with_the_folder_as_wsl_mounts_it():
    text = machine_renderer(machine_config()).render()["web.service"]

    assert "RequiresMountsFor=/mnt/c/www" in text.splitlines()
    assert exec_start(text) == (
        "ExecStart=/usr/bin/podman run --cidfile=%t/%N.cid --cgroups=enabled"
        " --sdnotify=conmon -d --replace --rm --name web -p 8080:80 -p 5353:53"
        " -v /mnt/c/www:/usr/share/nginx/html:ro -v webdata:/data"
        f" --env-file {ENV_DIR}/web.env docker.io/library/nginx"
    )


def test_a_mac_machine_unit_keeps_the_folder():
    config = PodmanConfig.from_dict(
        {
            "containers": [
                {"name": "site", "image": "nginx", "volumes": ["/Users/me:/s"]}
            ]
        }
    )

    text = machine_renderer(config, "darwin").render()["site.service"]

    assert "RequiresMountsFor=/Users/me" in text.splitlines()
    assert " --cgroups=enabled " in exec_start(text)
    assert " -v /Users/me:/s " in exec_start(text)


def test_the_linux_unit_runs_cgroups_split():
    linux = PodmanUnitRenderer(config=machine_config()).render()

    for text in linux.values():
        assert " --cgroups=split " in exec_start(text)
        assert "cgroups=enabled" not in text


def test_the_root_script_renders_the_golden_text_around_each_files_base64():
    config = machine_config(mirrors=["mirror.example"])
    script = PodmanMachineScriptRenderer(config=config, os_name="windows").render()
    payloads = ENCODED_PATTERN.findall(script)

    assert ENCODED_PATTERN.sub("'BASE64'", script) == (
        GOLDEN / "machine_script.sh"
    ).read_text(encoding="utf-8")
    renderer = machine_renderer(config)
    units = renderer.render()
    envs = renderer.environment_files()
    assert [base64.b64decode(payload).decode() for payload in payloads] == [
        units["web.service"],
        envs["web.env"],
        units["batch.service"],
        envs["batch.env"],
        PodmanRegistriesRenderer(config=config).render(),
    ]


# A systemctl that records each call and refuses a start or restart of a unit
# REFUSED names. A unit reads active when ACTIVE names it, until the script
# stops it; one the script starts or restarts reads active.
SYSTEMCTL_STUB = """#!/bin/sh
echo "$*" >> "$SYSTEMCTL_LOG"
state="$SYSTEMCTL_LOG.d"
mkdir -p "$state"
case "$1" in
is-active)
    [ -e "$state/$3.stopped" ] && exit 3
    [ -e "$state/$3.started" ] && exit 0
    case " $ACTIVE " in *" $3 "*) exit 0 ;; esac
    exit 3 ;;
stop)
    rm -f "$state/$2.started"
    touch "$state/$2.stopped" ;;
start|restart)
    case " $REFUSED " in *" $2 "*) echo "Job for $2 failed." >&2; exit 1 ;; esac
    rm -f "$state/$2.stopped"
    touch "$state/$2.started" ;;
esac
exit 0
"""


class MachineShell:
    """The root script run with ``sh`` against a temporary root, systemctl stubbed."""

    def __init__(self, tmp_path, os_name="windows"):
        self.os_name = os_name
        self.root = tmp_path / "machine"
        self.units = self.root / "etc/systemd/system"
        self.envs = self.root / ENV_DIR.lstrip("/")
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

    def run(
        self, config: PodmanConfig, *, active="", refused="", context=None
    ) -> tuple:
        self.log.write_text("")
        shutil.rmtree(f"{self.log}.d", ignore_errors=True)
        script = PodmanMachineScriptRenderer(
            config=config, os_name=self.os_name, root=str(self.root), context=context
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

    def run_script(self, script: str):
        self.log.write_text("")
        shutil.rmtree(f"{self.log}.d", ignore_errors=True)
        done = subprocess.run(
            ["sh", "-s"],
            input=script,
            capture_output=True,
            text=True,
            env={"PATH": self.path, "SYSTEMCTL_LOG": str(self.log)},
            timeout=60,
        )
        return done, self.log.read_text().splitlines()


def changed_lines(done) -> list:
    return [line for line in done.stdout.splitlines() if line.startswith("changed: ")]


def mode_of(path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


def test_the_script_writes_every_file_with_its_mode_and_restarts_what_starts_at_boot(
    tmp_path,
):
    shell = MachineShell(tmp_path)
    config = machine_config(mirrors=["mirror.example"])

    done, calls = shell.run(config)

    assert done.returncode == 0, done.stderr
    renderer = machine_renderer(config)
    for name in ("web", "batch"):
        assert (shell.units / f"{name}.service").read_text() == renderer.render()[
            f"{name}.service"
        ]
        assert (shell.envs / f"{name}.env").read_text() == (
            renderer.environment_files()[f"{name}.env"]
        )
        assert mode_of(shell.units / f"{name}.service") == 0o644
        assert mode_of(shell.envs / f"{name}.env") == 0o600
    assert mode_of(shell.envs) == 0o700
    assert shell.mirrors.read_text() == PodmanRegistriesRenderer(config=config).render()
    assert changed_lines(done) == [
        f"changed: {shell.units}/web.service",
        f"changed: {shell.envs}/web.env",
        f"changed: {shell.units}/batch.service",
        f"changed: {shell.envs}/batch.env",
        f"changed: {shell.mirrors}",
    ]
    assert calls == [
        "enable --no-reload web.service",
        "disable --no-reload batch.service",
        "daemon-reload",
        "is-active --quiet batch.service",
        "restart web.service",
    ]
    assert not list(shell.units.glob("*.new"))
    assert not list(shell.envs.glob("*.new"))


def test_an_unchanged_configuration_changes_nothing_and_restarts_nothing(tmp_path):
    shell = MachineShell(tmp_path)
    config = machine_config(mirrors=["mirror.example"])
    shell.run(config)

    done, calls = shell.run(config, active="web.service batch.service")

    assert done.returncode == 0, done.stderr
    assert changed_lines(done) == []
    assert calls == [
        "enable --no-reload web.service",
        "disable --no-reload batch.service",
        "daemon-reload",
        "is-active --quiet web.service",
    ]


def test_an_unchanged_container_started_at_boot_is_started_when_down(tmp_path):
    shell = MachineShell(tmp_path)
    config = machine_config()
    shell.run(config)

    done, calls = shell.run(config)

    assert done.returncode == 0, done.stderr
    assert changed_lines(done) == []
    assert calls[-2:] == ["is-active --quiet web.service", "start web.service"]


def test_a_changed_container_that_runs_restarts_though_not_started_at_boot(tmp_path):
    shell = MachineShell(tmp_path)
    shell.run(machine_config())
    changed = [MACHINE_CONTAINERS[0], dict(MACHINE_CONTAINERS[1], command="sleep 9")]

    done, calls = shell.run(machine_config(changed), active="batch.service")

    assert changed_lines(done) == [f"changed: {shell.units}/batch.service"]
    assert calls[2:] == [
        "daemon-reload",
        "is-active --quiet batch.service",
        "restart batch.service",
        "is-active --quiet web.service",
        "start web.service",
    ]


def test_a_changed_environment_alone_restarts_the_container(tmp_path):
    shell = MachineShell(tmp_path)
    shell.run(machine_config())
    changed = [dict(MACHINE_CONTAINERS[0], environment=["TZ=Asia/Shanghai"])]

    done, calls = shell.run(machine_config(changed), active="web.service")

    assert f"changed: {shell.envs}/web.env" in changed_lines(done)
    assert f"changed: {shell.units}/web.service" not in changed_lines(done)
    assert "restart web.service" in calls


def test_stale_generated_files_go_and_a_persons_own_file_stays(tmp_path):
    shell = MachineShell(tmp_path)
    shell.units.mkdir(parents=True)
    shell.envs.mkdir(parents=True)
    (shell.units / "old.service").write_text(f"{PODMAN_GENERATED_MARKER}\n[Unit]\n")
    (shell.envs / "old.env").write_text(f"{PODMAN_GENERATED_MARKER}\nA=1\n")
    (shell.envs / "orphan.env").write_text(f"{PODMAN_GENERATED_MARKER}\nA=1\n")
    (shell.units / "mine.service").write_text("[Unit]\nDescription=mine\n")
    shell.mirrors.parent.mkdir(parents=True)
    shell.mirrors.write_text(f"{PODMAN_GENERATED_MARKER}\n")

    done, calls = shell.run(machine_config())

    assert done.returncode == 0, done.stderr
    assert not (shell.units / "old.service").exists()
    assert not (shell.envs / "old.env").exists()
    assert not (shell.envs / "orphan.env").exists()
    assert (shell.units / "mine.service").read_text() == "[Unit]\nDescription=mine\n"
    assert not shell.mirrors.exists()
    assert f"changed: -{shell.units}/old.service" in changed_lines(done)
    assert f"changed: -{shell.envs}/orphan.env" in changed_lines(done)
    assert f"changed: -{shell.mirrors}" in changed_lines(done)
    assert "stop old.service" in calls
    assert "disable --no-reload old.service" in calls
    assert "stop mine.service" not in calls


def test_the_boot_unit_of_an_earlier_build_is_stopped_disabled_and_removed(tmp_path):
    shell = MachineShell(tmp_path, "darwin")
    shell.units.mkdir(parents=True)
    boot = shell.units / "neutrino_containers.service"
    boot.write_text(f"{PODMAN_GENERATED_MARKER}\n\n[Unit]\n")

    done, calls = shell.run(machine_config())

    assert done.returncode == 0, done.stderr
    assert not boot.exists()
    assert "stop neutrino_containers.service" in calls
    assert "disable --no-reload neutrino_containers.service" in calls


@pytest.mark.parametrize(
    "directory", ["usr/share/containers/systemd", "etc/containers/systemd"]
)
def test_an_earlier_build_s_quadlet_files_are_stopped_and_removed(tmp_path, directory):
    shell = MachineShell(tmp_path)
    quadlet = shell.root / directory
    quadlet.mkdir(parents=True)
    for name in ("web", "batch", "gone"):
        (quadlet / f"{name}.container").write_text(
            f"{PODMAN_GENERATED_MARKER}\n[Container]\n"
        )
    (quadlet / "mine.container").write_text("[Container]\nImage=mine\n")

    done, calls = shell.run(
        machine_config(), active="web.service batch.service gone.service"
    )

    assert done.returncode == 0, done.stderr
    assert sorted(path.name for path in quadlet.iterdir()) == ["mine.container"]
    for name in ("web", "batch", "gone"):
        assert f"stop {name}.service" in calls
        assert f"changed: -{quadlet}/{name}.container" in changed_lines(done)
    assert "stop mine.service" not in calls
    assert calls.index("stop batch.service") < calls.index("daemon-reload")
    assert "start gone.service" not in calls
    assert calls.index("start batch.service") > calls.index("daemon-reload")
    assert "start web.service" not in calls


def test_an_empty_configuration_takes_every_generated_file_away(tmp_path):
    shell = MachineShell(tmp_path)
    shell.run(machine_config(mirrors=["mirror.example"]))

    done, calls = shell.run(PodmanConfig())

    assert done.returncode == 0, done.stderr
    assert list(shell.units.iterdir()) == []
    assert list(shell.envs.iterdir()) == []
    assert not shell.mirrors.exists()
    assert calls == [
        "stop batch.service",
        "disable --no-reload batch.service",
        "stop web.service",
        "disable --no-reload web.service",
        "daemon-reload",
    ]


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


def test_the_stop_script_stops_each_generated_container_and_keeps_its_files(
    tmp_path,
):
    shell = MachineShell(tmp_path)
    shell.run(machine_config())
    (shell.units / "mine.service").write_text("[Unit]\n")

    done, calls = shell.run_script(machine_stop_script(root=str(shell.root)))

    assert done.returncode == 0, done.stderr
    assert calls == ["stop batch.service", "stop web.service"]
    assert (shell.units / "web.service").exists()
    assert (shell.envs / "web.env").exists()


# --- hub containers ---

HUB_DIGEST = "sha256:" + "e" * 64

HUB_CONTAINERS = [
    {
        "module": "demo",
        "name": "neutrino_demo_agent",
        "image": {"digest": HUB_DIGEST, "sources": ["docker.io/acme/agent"]},
        "volumes": ["neutrino_demo_home:/opt/data"],
        "environment": ["HOME_DIR=/opt/data"],
        "command": "gateway run",
        "source_sets": ["pypi"],
    },
    {
        "module": "demo",
        "name": "neutrino_demo",
        "image": {
            "digest": HUB_DIGEST,
            "sources": ["ghcr.io/acme/webui", "ghcr.nju.edu.cn/acme/webui"],
        },
        "volumes": ["neutrino_demo_home:/home/web/.data"],
        "environment": ["PASSWORD=s3cret", "EXTRA_INDEX={pypi}/extra"],
        "is_autostart": False,
        "source_sets": ["pypi"],
        "after": ["neutrino_demo_agent"],
        "page_port": 8787,
    },
]

HUB_CONTEXT = PodmanRenderContext(
    gateways={"podman": "10.88.0.1", "neutrino_demo": "10.89.0.1"},
    images={
        "neutrino_demo_agent": "docker.io/acme/agent@" + HUB_DIGEST,
        "neutrino_demo": "ghcr.nju.edu.cn/acme/webui@" + HUB_DIGEST,
    },
    page_ports={"neutrino_demo": 40123},
    sources={"pypi": "https://pypi.tuna.example/simple"},
    variables={"pypi": ["PIP_INDEX_URL", "UV_DEFAULT_INDEX"]},
)


def hub_config(containers=None, hub=None) -> PodmanConfig:
    config = PodmanConfig.from_dict(
        {
            "containers": [] if containers is None else containers,
            "hub_containers": HUB_CONTAINERS if hub is None else hub,
        }
    )
    config.validate()
    return config


def other_sources() -> PodmanRenderContext:
    return PodmanRenderContext(
        gateways=HUB_CONTEXT.gateways,
        images=HUB_CONTEXT.images,
        page_ports=HUB_CONTEXT.page_ports,
        sources={"pypi": "https://pypi.org/simple"},
        variables=HUB_CONTEXT.variables,
    )


def test_a_hub_container_has_its_label_network_gateway_image_and_page_port():
    renderer = PodmanUnitRenderer(config=hub_config(), context=HUB_CONTEXT)
    text = renderer.render()["neutrino_demo.service"]

    assert text.splitlines()[3:8] == [
        "Description=neutrino_demo container",
        "Wants=network-online.target",
        "After=network-online.target",
        "Requires=neutrino_demo_agent.service",
        "After=neutrino_demo_agent.service",
    ]
    assert exec_start(text) == (
        "ExecStart=/usr/bin/podman run --cidfile=%t/%N.cid --cgroups=split"
        " --sdnotify=conmon -d --replace --rm --name neutrino_demo"
        " --label neutrino.module=demo --network neutrino_demo"
        " --add-host host.containers.internal:10.89.0.1"
        " -p 127.0.0.1:40123:8787 -v neutrino_demo_home:/home/web/.data"
        f" --env-file {ENV_DIR}/neutrino_demo.env"
        " ghcr.nju.edu.cn/acme/webui@" + HUB_DIGEST
    )
    assert renderer.environment_files()["neutrino_demo.env"] == (
        f"{PODMAN_GENERATED_MARKER}\n"
        "PASSWORD=s3cret\n"
        "EXTRA_INDEX=https://pypi.tuna.example/simple/extra\n"
        "PIP_INDEX_URL=https://pypi.tuna.example/simple\n"
        "UV_DEFAULT_INDEX=https://pypi.tuna.example/simple\n"
    )
    assert "s3cret" not in text


def test_a_declared_container_reaches_the_machine_at_its_network_s_gateway():
    rendered = PodmanUnitRenderer(
        config=hub_config([FULL], hub=[]), context=HUB_CONTEXT
    ).render()
    line = exec_start(rendered["webdav.service"])

    assert " --add-host host.containers.internal:10.88.0.1 " in line
    assert "--label" not in line
    assert "--network" not in line


def test_no_gateway_known_writes_no_add_host():
    rendered = PodmanUnitRenderer(config=hub_config([FULL])).render()

    assert not any("--add-host" in text for text in rendered.values())


def test_a_hub_container_with_no_stored_image_names_its_first_source_by_digest():
    text = PodmanUnitRenderer(config=hub_config()).render()["neutrino_demo.service"]

    assert exec_start(text).endswith(" ghcr.io/acme/webui@" + HUB_DIGEST)
    assert " -p " not in exec_start(text)


def test_the_source_keys_are_the_variables_a_set_fills_in():
    renderer = PodmanUnitRenderer(config=hub_config(), context=HUB_CONTEXT)

    assert renderer.source_keys() == {
        "neutrino_demo_agent": ["PIP_INDEX_URL", "UV_DEFAULT_INDEX"],
        "neutrino_demo": ["EXTRA_INDEX", "PIP_INDEX_URL", "UV_DEFAULT_INDEX"],
    }


def test_two_environment_files_that_differ_in_a_set_s_value_alone_read_the_same():
    keys = ["EXTRA_INDEX", "PIP_INDEX_URL", "UV_DEFAULT_INDEX"]
    first = PodmanUnitRenderer(config=hub_config(), context=HUB_CONTEXT)
    second = PodmanUnitRenderer(config=hub_config(), context=other_sources())
    first_env = first.environment_files()["neutrino_demo.env"]
    second_env = second.environment_files()["neutrino_demo.env"]

    assert first.render() == second.render()
    assert first_env != second_env
    assert source_neutral(first_env, keys) == source_neutral(second_env, keys)
    assert source_neutral(first_env, keys) != source_neutral(
        first_env.replace("s3cret", "other"), keys
    )


def test_the_machine_unit_of_a_hub_container_has_no_add_host_and_cgroups_enabled():
    text = machine_renderer(hub_config(), "darwin", HUB_CONTEXT).render()[
        "neutrino_demo.service"
    ]

    assert "--add-host" not in text
    assert " --cgroups=enabled " in exec_start(text)
    assert " -p 127.0.0.1:40123:8787 " in exec_start(text)


def test_the_root_script_keeps_a_file_whose_only_change_is_a_set_s_value(tmp_path):
    shell = MachineShell(tmp_path, "darwin")
    done, _calls = shell.run(hub_config(), context=HUB_CONTEXT)
    assert done.returncode == 0, done.stderr
    first = (shell.envs / "neutrino_demo.env").read_text()

    done, calls = shell.run(
        hub_config(), context=other_sources(), active="neutrino_demo.service"
    )

    assert done.returncode == 0, done.stderr
    assert changed_lines(done) == []
    assert (shell.envs / "neutrino_demo.env").read_text() == first
    assert not any(call.startswith("restart") for call in calls)


def test_the_root_script_starts_a_hub_container_that_starts_with_the_box(tmp_path):
    shell = MachineShell(tmp_path, "windows")

    done, calls = shell.run(hub_config(), context=HUB_CONTEXT)

    assert done.returncode == 0, done.stderr
    assert "restart neutrino_demo_agent.service" in calls
    assert "restart neutrino_demo.service" not in calls


def test_the_drop_script_removes_only_the_named_generated_files(tmp_path):
    shell = MachineShell(tmp_path, "windows")
    shell.run(hub_config(), context=HUB_CONTEXT)
    (shell.units / "theirs.service").write_text("[Unit]\n")

    done, calls = shell.run_script(
        machine_drop_script(
            ["neutrino_demo", "neutrino_demo_agent", "theirs"], root=str(shell.root)
        )
    )

    assert done.returncode == 0, done.stderr
    assert sorted(path.name for path in shell.units.iterdir()) == ["theirs.service"]
    assert list(shell.envs.iterdir()) == []
    assert "stop neutrino_demo.service" in calls
    assert "disable --no-reload neutrino_demo.service" in calls
    assert "stop theirs.service" not in calls
    assert calls[-1] == "daemon-reload"

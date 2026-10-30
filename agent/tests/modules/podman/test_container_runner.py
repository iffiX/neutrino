"""The ``container`` method: images pulled by digest from the fastest source, run as hub containers."""

import contextlib
import functools
import json
import subprocess

import pytest

from neutrino_agent.exceptions import ModuleApplyError, ModuleInstallPending
from neutrino_agent.modules.podman import container_runner as container_runner_module
from neutrino_agent.modules.podman.container_runner import (
    ContainerHooks,
    ContainerModuleRunner,
    recipe_images,
)
from neutrino_agent.modules.shared.source_fetch import SourceProbe
from neutrino_agent.modules.shared.subprocess_run import CommandResult
from neutrino_agent.platforms.base import AgentPlatform

WEB = "sha256:" + "a" * 64
AGENT = "sha256:" + "b" * 64

RECIPE = {
    "runner": "container",
    "method": "container",
    "params": {
        "version": "0.52.492",
        "artifacts": [
            {
                "name": "webui",
                "kind": "image",
                "digest": WEB,
                "sources": ["ghcr.io/acme/webui", "ghcr.nju.edu.cn/acme/webui"],
            },
            {
                "name": "agent",
                "kind": "image",
                "digest": AGENT,
                "sources": ["docker.io/acme/agent"],
            },
        ],
        "source_sets": ["pypi"],
    },
}


class FakeContainers:
    """The Containers runner as a container module reaches it."""

    def __init__(self, *, hub_names=None, is_active=True, is_written=True):
        self.command = ("/usr/bin/podman",)
        self.names = dict(hub_names or {})
        self.is_active = is_active
        self.is_written = is_written
        self.driven: list = []
        self.dropped: list = []
        self.is_awake = False
        # Whether the engine was held awake at each drop.
        self.awake_at_drop: list = []

    def podman_command(self):
        return self.command

    def hub_names(self):
        return dict(self.names)

    def is_applied(self, module):
        return self.is_written

    def is_engine_active(self):
        return self.is_active

    def drive_hub_containers(self, names, action):
        self.driven.append((list(names), action))

    def image_references(self):
        if not self.command:
            return set()
        return container_runner_module.image_references(podman=self.command)

    def drop_hub_containers(self, module):
        self.dropped.append(module)
        self.awake_at_drop.append(self.is_awake)
        self.names.pop(module, None)

    @contextlib.contextmanager
    def engine_awake(self):
        self.is_awake = True
        try:
            yield
        finally:
            self.is_awake = False

    def hub_journal(self, names, lines):
        return [f"{name}: line" for name in names]


class FakePodman:
    """podman's answers: what ``ps`` lists, what ``volume ls`` lists, which pulls fail."""

    def __init__(self, *, running=(), stopped=(), volumes=(), failing=(), on_rmi=None):
        self.running = list(running)
        self.stopped = list(stopped)
        self.volumes = list(volumes)
        self.failing = set(failing)
        # Called with each reference ``rmi`` names.
        self.on_rmi = on_rmi
        self.calls: list = []
        # Whether the engine is held awake, asked at each call; None asks nothing.
        self.is_awake = None
        self.awake_at_calls: list = []

    def __call__(self, command, *, is_checked=True, input_text=None, timeout_s=120):
        self.calls.append(list(command))
        if self.is_awake is not None:
            self.awake_at_calls.append(self.is_awake())
        verb = command[1]
        if verb == "ps":
            entries = [{"Names": [n], "State": "running"} for n in self.running]
            entries += [{"Names": [n], "State": "exited"} for n in self.stopped]
            return CommandResult(list(command), 0, json.dumps(entries), "")
        if verb == "volume" and command[2] == "ls":
            listed = [{"Name": name} for name in self.volumes]
            return CommandResult(list(command), 0, json.dumps(listed), "")
        if verb == "rmi" and self.on_rmi is not None:
            self.on_rmi(command[2])
        if verb == "pull" and command[2] in self.failing:
            if is_checked:
                raise subprocess.CalledProcessError(
                    125, list(command), stderr="Error: manifest unknown"
                )
        return CommandResult(list(command), 0, "", "")


def answering(speeds):
    """A probe whose sources answer at these speeds; a source missing is unreachable."""

    def probe_one(url, *, source="", headers=None):
        speed = speeds.get(source)
        if speed is None:
            return SourceProbe(source=source, reason="unreachable", detail="refused")
        return SourceProbe(source=source, is_answered=True, speed=speed, status=200)

    return probe_one


@pytest.fixture
def store(monkeypatch):
    """The references the store holds, which a test fills in."""
    held: set = set()
    monkeypatch.setattr(
        container_runner_module, "image_references", lambda *, podman: set(held)
    )
    monkeypatch.setattr(
        container_runner_module, "read_image_references", lambda *, podman: set(held)
    )
    return held


def runner_for(containers, podman, probe_one=None, lines=None):
    return ContainerModuleRunner(
        platform=AgentPlatform(),
        name="demo",
        containers=containers,
        log=(lines.append if lines is not None else lambda line: None),
        probe_one=probe_one or answering({}),
        run_command=podman,
    )


def test_the_recipe_s_images_are_its_image_artifacts():
    assert [image["name"] for image in recipe_images(RECIPE)] == ["webui", "agent"]
    assert recipe_images({"params": {}}) == []


def test_present_means_every_pinned_image_is_in_the_store(store):
    runner = runner_for(FakeContainers(), FakePodman())
    assert runner.verify(RECIPE) is False

    store.add("ghcr.nju.edu.cn/acme/webui@" + WEB)
    assert runner.verify(RECIPE) is False

    store.add("docker.io/acme/agent@" + AGENT)
    assert runner.verify(RECIPE) is True


def test_no_podman_to_ask_is_not_present(store):
    containers = FakeContainers()
    containers.command = ()

    assert runner_for(containers, FakePodman()).verify(RECIPE) is False


def test_an_install_pulls_each_missing_image_by_digest_from_the_fastest_source(store):
    store.add("docker.io/acme/agent@" + AGENT)
    podman = FakePodman()
    probe = answering({"ghcr.io/acme/webui": 1.0, "ghcr.nju.edu.cn/acme/webui": 9.0})
    lines: list = []

    runner_for(FakeContainers(), podman, probe, lines).install(RECIPE)

    pulls = [call for call in podman.calls if call[1] == "pull"]
    assert pulls == [["/usr/bin/podman", "pull", "ghcr.nju.edu.cn/acme/webui@" + WEB]]
    assert lines == ["demo: pulling ghcr.nju.edu.cn/acme/webui@" + WEB]


def test_a_failed_pull_goes_on_to_the_next_source(store):
    store.add("docker.io/acme/agent@" + AGENT)
    podman = FakePodman(failing={"ghcr.nju.edu.cn/acme/webui@" + WEB})
    probe = answering({"ghcr.io/acme/webui": 1.0, "ghcr.nju.edu.cn/acme/webui": 9.0})

    runner_for(FakeContainers(), podman, probe).install(RECIPE)

    pulls = [call[2] for call in podman.calls if call[1] == "pull"]
    assert pulls == [
        "ghcr.nju.edu.cn/acme/webui@" + WEB,
        "ghcr.io/acme/webui@" + WEB,
    ]


def test_no_source_serving_an_image_is_download_failed_with_each_pull(store):
    """Only a pull's own failure is listed; a probe that got no answer is not."""
    store.add("docker.io/acme/agent@" + AGENT)
    podman = FakePodman(
        failing={"ghcr.io/acme/webui@" + WEB, "ghcr.nju.edu.cn/acme/webui@" + WEB}
    )
    probe = answering({"ghcr.io/acme/webui": 1.0})

    with pytest.raises(ModuleApplyError) as refused:
        runner_for(FakeContainers(), podman, probe).install(RECIPE)

    assert refused.value.code == "download_failed"
    assert refused.value.params == {
        "file": "ghcr.io/acme/webui@" + WEB,
        "sources": [
            {
                "source": "ghcr.io/acme/webui",
                "reason": "pull_failed",
                "detail": "Error: manifest unknown",
            },
            {
                "source": "ghcr.nju.edu.cn/acme/webui",
                "reason": "pull_failed",
                "detail": "Error: manifest unknown",
            },
        ],
    }


def test_a_source_the_probe_missed_is_pulled_after_the_ranked_ones(store):
    """On Windows the probe of docker.io failed CERTIFICATE_VERIFY_FAILED while
    Podman in the machine pulled the image."""
    store.add("docker.io/acme/agent@" + AGENT)
    podman = FakePodman(failing={"ghcr.io/acme/webui@" + WEB})
    probe = answering({"ghcr.io/acme/webui": 1.0})

    runner_for(FakeContainers(), podman, probe).install(RECIPE)

    pulls = [call[2] for call in podman.calls if call[1] == "pull"]
    assert pulls == [
        "ghcr.io/acme/webui@" + WEB,
        "ghcr.nju.edu.cn/acme/webui@" + WEB,
    ]


def test_an_install_with_no_podman_is_install_failed(store):
    containers = FakeContainers()
    containers.command = ()

    with pytest.raises(ModuleApplyError) as refused:
        runner_for(containers, FakePodman()).install(RECIPE)

    assert refused.value.code == "install_failed"


def test_a_start_waits_until_containers_renders_the_module(store):
    with pytest.raises(ModuleInstallPending):
        runner_for(FakeContainers(), FakePodman()).start()


def test_a_start_starts_the_containers_that_do_not_run(store):
    containers = FakeContainers(
        hub_names={"demo": ["neutrino_demo_agent", "neutrino_demo"]}
    )
    podman = FakePodman(running=["neutrino_demo_agent"], stopped=["neutrino_demo"])

    runner_for(containers, podman).start()

    assert containers.driven == [(["neutrino_demo"], "start")]
    assert ["--filter", "label=neutrino.module=demo"] == [
        call for call in podman.calls if call[1] == "ps"
    ][0][3:5]


def test_a_start_fails_while_containers_has_not_written_the_module_s_containers(
    store, monkeypatch
):
    """Containers' last apply failed before it wrote the units and environment
    files the state names, so the module's containers run on earlier ones."""
    containers = FakeContainers(hub_names={"demo": ["neutrino_demo"]}, is_written=False)
    told: list = []
    monkeypatch.setattr(ContainerHooks, "installed", lambda self, v: told.append(v))
    monkeypatch.setattr(ContainerHooks, "start", lambda self: told.append("start"))
    runner = runner_for(containers, FakePodman(stopped=["neutrino_demo"]))
    runner.take_recipe(RECIPE)

    with pytest.raises(ModuleApplyError) as refused:
        runner.start()

    assert (refused.value.code, refused.value.params) == ("containers_not_applied", {})
    assert containers.driven == []
    assert told == []


def test_a_start_leaves_the_containers_while_containers_is_stopped(store):
    containers = FakeContainers(hub_names={"demo": ["neutrino_demo"]}, is_active=False)

    runner_for(containers, FakePodman(stopped=["neutrino_demo"])).start()

    assert containers.driven == []


def test_running_means_every_container_of_the_module_runs(store):
    containers = FakeContainers(
        hub_names={"demo": ["neutrino_demo_agent", "neutrino_demo"]}
    )

    both = runner_for(
        containers, FakePodman(running=["neutrino_demo_agent", "neutrino_demo"])
    )
    one = runner_for(containers, FakePodman(running=["neutrino_demo_agent"]))
    none = runner_for(FakeContainers(), FakePodman())

    assert both.is_active() is True
    assert one.is_active() is False
    assert none.is_active() is False


def test_a_stop_stops_the_module_s_containers(store):
    containers = FakeContainers(hub_names={"demo": ["neutrino_demo"]})

    runner_for(containers, FakePodman()).stop()

    assert containers.driven == [(["neutrino_demo"], "stop")]


def test_a_refused_stop_keeps_systemd_s_own_words(store):
    class Refusing(FakeContainers):
        def drive_hub_containers(self, names, action):
            raise subprocess.CalledProcessError(
                1, ["systemctl", "stop"], stderr="Job for x.service canceled.\n"
            )

    containers = Refusing(hub_names={"demo": ["neutrino_demo"]})

    with pytest.raises(ModuleApplyError) as refused:
        runner_for(containers, FakePodman()).stop()

    assert refused.value.code == "apply_failed"
    assert refused.value.params == {"detail": "Job for x.service canceled."}


def test_the_uninstall_removes_containers_units_network_volumes_and_images(store):
    store.update({"ghcr.io/acme/webui@" + WEB, "docker.io/acme/agent@" + AGENT})
    containers = FakeContainers(hub_names={"demo": ["neutrino_demo"]})
    podman = FakePodman(
        stopped=["neutrino_demo"],
        volumes=[
            "neutrino_demo_home",
            "neutrino_demo_app",
            "neutrino_other_home",
            "mine",
        ],
    )

    runner_for(containers, podman).uninstall(RECIPE)

    assert containers.dropped == ["demo"]
    removals = [call[1:] for call in podman.calls if call[1] != "ps"]
    assert removals == [
        ["rm", "-f", "neutrino_demo"],
        ["network", "rm", "neutrino_demo"],
        ["volume", "ls", "--format", "json"],
        ["volume", "rm", "-f", "neutrino_demo_home"],
        ["volume", "rm", "-f", "neutrino_demo_app"],
        ["rmi", "ghcr.io/acme/webui@" + WEB],
        ["rmi", "docker.io/acme/agent@" + AGENT],
    ]


def test_the_uninstall_holds_the_engine_awake_through_every_step(store):
    containers = FakeContainers(hub_names={"demo": ["neutrino_demo"]})
    podman = FakePodman(stopped=["neutrino_demo"], volumes=["neutrino_demo_home"])
    podman.is_awake = functools.partial(getattr, containers, "is_awake")

    runner_for(containers, podman).uninstall(RECIPE)

    assert containers.awake_at_drop == [True]
    assert podman.awake_at_calls
    assert all(podman.awake_at_calls)
    assert containers.is_awake is False


def test_the_uninstall_removes_an_earlier_version_s_image_and_no_other(store):
    older = "sha256:" + "e" * 64
    store.update(
        {
            "ghcr.io/acme/webui@" + WEB,
            "ghcr.nju.edu.cn/acme/webui@" + older,
            "docker.io/acme/agent@" + AGENT,
            "docker.io/someone/webui@" + older,
        }
    )
    podman = FakePodman()

    runner_for(FakeContainers(), podman).uninstall(RECIPE)

    assert [call[1:] for call in podman.calls if call[1] == "rmi"] == [
        ["rmi", "ghcr.io/acme/webui@" + WEB],
        ["rmi", "ghcr.nju.edu.cn/acme/webui@" + older],
        ["rmi", "docker.io/acme/agent@" + AGENT],
    ]


def test_the_uninstall_removes_an_image_of_two_references_once(store):
    index = "sha256:" + "f" * 64
    webui = {"ghcr.io/acme/webui@" + WEB, "ghcr.io/acme/webui@" + index}
    store.update(webui | {"docker.io/acme/agent@" + AGENT})
    podman = FakePodman(
        on_rmi=lambda reference: store.difference_update(
            webui if reference in webui else {reference}
        )
    )

    runner_for(FakeContainers(), podman).uninstall(RECIPE)

    assert [call[1:] for call in podman.calls if call[1] == "rmi"] == [
        ["rmi", "ghcr.io/acme/webui@" + WEB],
        ["rmi", "docker.io/acme/agent@" + AGENT],
    ]
    assert store == set()


def test_the_details_name_the_version_and_the_journal_is_the_containers(store):
    containers = FakeContainers(
        hub_names={"demo": ["neutrino_demo_agent", "neutrino_demo"]}
    )
    runner = runner_for(containers, FakePodman())

    assert runner.details(RECIPE) == {"version": "0.52.492"}
    assert runner.journal_text(10) == [
        "neutrino_demo_agent: line",
        "neutrino_demo: line",
    ]


def test_a_module_s_hooks_are_called_where_the_runner_says(store, monkeypatch):
    calls: list = []

    class DemoHooks(ContainerHooks):
        def apply(self, config):
            calls.append(("apply", config))

        def start(self):
            calls.append(("start",))

        def details(self):
            return {"port": 8787}

        def remove(self):
            calls.append(("remove",))

    monkeypatch.setitem(
        container_runner_module.CONTAINER_MODULE_HOOKS, "demo", DemoHooks
    )
    containers = FakeContainers(hub_names={"demo": ["neutrino_demo"]})
    runner = runner_for(containers, FakePodman(running=["neutrino_demo"]))

    runner.apply({"port": 8787})
    runner.start()
    runner.uninstall(RECIPE)

    assert calls == [("apply", {"port": 8787}), ("start",), ("remove",)]
    assert runner.details(RECIPE) == {"version": "0.52.492", "port": 8787}


def test_each_start_tells_the_hooks_the_recipe_s_version_first(store, monkeypatch):
    calls: list = []

    class DemoHooks(ContainerHooks):
        def installed(self, version):
            calls.append(("installed", version))

        def start(self):
            calls.append(("start",))

    monkeypatch.setitem(
        container_runner_module.CONTAINER_MODULE_HOOKS, "demo", DemoHooks
    )
    containers = FakeContainers(hub_names={"demo": ["neutrino_demo"]})
    runner = runner_for(containers, FakePodman(running=["neutrino_demo"]))

    runner.take_recipe(RECIPE)
    runner.start()

    assert calls == [("installed", "0.52.492"), ("start",)]


def test_the_state_s_source_sets_reach_the_module_s_hooks(store, monkeypatch):
    taken: list = []

    class DemoHooks(ContainerHooks):
        def take_source_sets(self, source_sets):
            taken.append(source_sets)

    monkeypatch.setitem(
        container_runner_module.CONTAINER_MODULE_HOOKS, "demo", DemoHooks
    )
    runner = runner_for(FakeContainers(), FakePodman())
    sets = {"ctan": {"probe": "/x", "sources": ["https://a.example"], "variables": []}}

    runner.take_source_sets(sets)
    runner_for(FakeContainers(), FakePodman()).take_source_sets({})

    assert taken == [sets, {}]


def test_an_install_tells_the_hooks_its_version_and_installing_is_theirs(
    store, monkeypatch
):
    calls: list = []

    class DemoHooks(ContainerHooks):
        def installed(self, version):
            calls.append(("installed", version))

        def is_installing(self):
            return True

    monkeypatch.setitem(
        container_runner_module.CONTAINER_MODULE_HOOKS, "demo", DemoHooks
    )
    store.add("docker.io/acme/agent@" + AGENT)
    store.add("ghcr.io/acme/webui@" + WEB)
    runner = runner_for(FakeContainers(), FakePodman())

    runner.install(RECIPE)

    assert calls == [("installed", "0.52.492")]
    assert runner.is_installing() is True
    assert runner_for(FakeContainers(), FakePodman()).is_installing() is True
    monkeypatch.delitem(container_runner_module.CONTAINER_MODULE_HOOKS, "demo")
    assert runner_for(FakeContainers(), FakePodman()).is_installing() is False

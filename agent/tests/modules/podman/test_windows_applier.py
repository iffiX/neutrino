"""The Windows part of a Podman machine: the features and the msis through
faked dism and msiexec, the reboot mark across a faked boot, the account's
.wslconfig merged, the WSL disk read and resized, and the uninstall."""

import os
import struct
import subprocess
import uuid

import pytest

from neutrino_agent.exceptions import InstallError, ModuleApplyError
from neutrino_agent.modules.podman.machine_runner import podman_system_applier_for
from neutrino_agent.modules.podman.windows_applier import (
    PodmanWindowsApplier,
    merged_wslconfig,
    version_numbers,
    vhdx_virtual_size,
    wsl_script,
)
from neutrino_agent.modules.shared.subprocess_run import CommandResult
from neutrino_agent.platforms.base import AgentPlatform

GIB = 1024**3
WSL_CODE = "{2D92E6AF-35B2-4109-893F-59E4A4F2D550}"
PODMAN_CODE = "{E8D285D4-F069-44B9-BF8A-C41ED47B02B8}"
DISM_HEAD = ["/English", "/Online", "/Enable-Feature"]
DISM_TAIL = ["/All", "/NoRestart"]
WSL_ARTIFACT = {"name": "wsl", "kind": "msi", "directory": "wsl"}
PODMAN_ARTIFACT = {"name": "podman", "kind": "msi", "directory": "podman"}


class Platform(AgentPlatform):
    """A Windows computer whose state root and homes are folders of the test."""

    os_name = "windows"

    def __init__(self, root):
        self._root = str(root)

    def agent_var_dir(self):
        return os.path.join(self._root, "state")

    def account_home(self, account):
        if account != "lab":
            raise KeyError(account)
        return os.path.join(self._root, "Users", account)


class Machine:
    """The account's machine as the applier drives it: wsl.exe and its own
    code run as the account, recorded."""

    def __init__(self, account="lab", answers=()):
        self.account = account
        self.runs: list = []
        self.steps: list = []
        self.answers = list(answers)

    def run_as_account(self, argv, *, stdin="", timeout_s=0):
        self.runs.append(list(argv))
        answer = self.answers.pop(0) if self.answers else (0, "")
        if isinstance(answer, BaseException):
            raise answer
        code, output = answer
        return subprocess.CompletedProcess(list(argv), code, output, "")

    def as_account(self, step, *arguments):
        self.steps.append((self.account, step.__name__))
        return step(*arguments)


class Rig:
    """One applier with dism, msiexec, the registry and the clock faked."""

    def __init__(self, tmp_path):
        self.tmp_path = tmp_path
        self.platform = Platform(tmp_path)
        self.lines: list = []
        self.dism_codes: dict = {}
        self.dism_calls: list = []
        self.installs: list = []
        self.install_answers: dict = {}
        self.uninstalls: list = []
        self.uninstall_answers: dict = {}
        self.products: list = [
            {"code": WSL_CODE, "name": "Windows Subsystem for Linux", "version": ""},
        ]
        self.is_key = False
        self.boot = [1_000_000.0]
        self.memory = 6 * GIB - 200 * 1024**2
        self.applier = self.make()

    def make(self):
        return PodmanWindowsApplier(
            platform=self.platform,
            log=self.lines.append,
            run=self.dism,
            install_msi=self.install_msi,
            uninstall_msi=self.uninstall_msi,
            read_products=lambda: [dict(product) for product in self.products],
            has_restart_key=lambda: self.is_key,
            read_boot_time=lambda: self.boot[0],
            read_memory_bytes=lambda: self.memory,
            join=os.path.join,
        )

    def dism(self, command, *, is_checked=True, timeout_s=0, **_):
        self.dism_calls.append(list(command))
        feature = command[4].split(":", 1)[1]
        answer = self.dism_codes.get(feature, 0)
        if isinstance(answer, BaseException):
            raise answer
        return CommandResult(list(command), answer, "", "")

    def install_msi(self, path, *, log_path, properties=()):
        self.installs.append((os.path.basename(path), log_path, tuple(properties)))
        answer = self.install_answers.get(os.path.basename(path), 0)
        if answer not in (0, 3010):
            raise InstallError(f"msiexec exited {answer}", exit_code=answer)
        return answer == 3010

    def uninstall_msi(self, product_code, *, log_path):
        self.uninstalls.append(product_code)
        answer = self.uninstall_answers.get(product_code, 0)
        if answer not in (0, 3010):
            raise InstallError(f"msiexec exited {answer}", exit_code=answer)
        return answer == 3010

    def keep(self, artifact):
        directory = self.tmp_path / "state" / "podman" / artifact["directory"]
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{artifact['name']}.msi"
        path.write_bytes(b"msi")
        return str(path)

    def install(self, artifact):
        self.applier.install_artifact(dict(artifact), self.keep(artifact))

    def mark(self):
        return self.tmp_path / "state" / "podman" / "reboot_mark"

    def home(self):
        home = self.tmp_path / "Users" / "lab"
        home.mkdir(parents=True, exist_ok=True)
        return home


@pytest.fixture
def rig(tmp_path):
    return Rig(tmp_path)


def refusal(step) -> ModuleApplyError:
    with pytest.raises(ModuleApplyError) as refused:
        step()
    return refused.value


def vhdx(size: int) -> bytes:
    """A VHDX disk's head: the signature, a region table and the metadata
    table naming one virtual size."""
    data = bytearray(0x60000 + 8)
    data[0:8] = b"vhdxfile"
    metadata_at = 0x50000
    struct.pack_into("<4sIII", data, 0x30000, b"regi", 0, 2, 0)
    other = uuid.UUID("2DC27766-F623-4200-9D64-115E9BFD4A08").bytes_le
    struct.pack_into("<16sQII", data, 0x30010, other, 0x300000, 0x100000, 1)
    metadata = uuid.UUID("8B7CA206-4790-4B9A-B8FE-575F050F886E").bytes_le
    struct.pack_into("<16sQII", data, 0x30030, metadata, metadata_at, 0x10000, 1)
    struct.pack_into("<8sHH", data, metadata_at, b"metadata", 0, 2)
    block = uuid.UUID("CAA16737-FA36-4D43-B3B6-33F0AA44E76B").bytes_le
    struct.pack_into("<16sIIII", data, metadata_at + 32, block, 0x10008, 8, 4, 0)
    item = uuid.UUID("2FA54224-CD1B-4876-B211-5DBED83BF4B8").bytes_le
    struct.pack_into("<16sIIII", data, metadata_at + 64, item, 0x10000, 8, 6, 0)
    struct.pack_into("<Q", data, metadata_at + 0x10000, size)
    return bytes(data)


# --- what the applier is ---


def test_windows_gets_the_wsl_applier_with_podmans_program_under_program_files(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("ProgramFiles", "D:\\Apps")

    applier = podman_system_applier_for(Platform(tmp_path))

    assert isinstance(applier, PodmanWindowsApplier)
    assert applier.provider == "wsl"
    assert applier.binary == "D:\\Apps\\Podman\\podman.exe"


# --- the features and the msis ---


def test_both_features_are_turned_on_once_before_the_first_msi(rig):
    rig.install(WSL_ARTIFACT)
    rig.install(PODMAN_ARTIFACT)

    assert [call[1:] for call in rig.dism_calls] == [
        DISM_HEAD + ["/FeatureName:VirtualMachinePlatform"] + DISM_TAIL,
        DISM_HEAD + ["/FeatureName:Microsoft-Windows-Subsystem-Linux"] + DISM_TAIL,
    ]
    assert all(
        call[0].lower().endswith("\\system32\\dism.exe") for call in rig.dism_calls
    )
    assert not rig.mark().exists()


def test_a_feature_that_owes_a_restart_writes_the_mark_with_this_boot(rig):
    rig.dism_codes["VirtualMachinePlatform"] = 3010

    rig.install(WSL_ARTIFACT)

    assert rig.mark().read_text().strip() == "1000000"
    assert rig.applier.is_reboot_pending()
    assert [name for name, _log, _properties in rig.installs] == ["wsl.msi"]


@pytest.mark.parametrize("answer, exit_code", [(87, 87), (OSError("gone"), -1)])
def test_a_feature_dism_refuses_ends_the_install_with_its_exit_code(
    rig, answer, exit_code
):
    rig.dism_codes["Microsoft-Windows-Subsystem-Linux"] = answer

    refused = refusal(lambda: rig.install(WSL_ARTIFACT))

    assert refused.code == "windows_feature_failed"
    assert refused.params == {
        "feature": "Microsoft-Windows-Subsystem-Linux",
        "exit_code": exit_code,
    }
    assert rig.installs == []


@pytest.mark.parametrize("version", ["", "2.6.1.0", "3.0.2.0"])
def test_the_wsl_msi_runs_when_no_wsl_or_an_older_one_is_installed(rig, version):
    rig.products[0]["version"] = version
    if not version:
        rig.products.clear()

    rig.install(WSL_ARTIFACT)

    name, log_path, properties = rig.installs[0]
    assert name == "wsl.msi"
    assert properties == ()
    assert log_path.endswith(os.path.join("wsl", "wsl.log"))
    assert "podman: installed wsl" in rig.lines


@pytest.mark.parametrize("version", ["3.0.3.0", "3.0.3", "3.1.0.0", "10.0.0"])
def test_the_wsl_msi_is_skipped_at_the_pinned_version_or_newer(rig, version):
    rig.products[0]["version"] = version

    rig.install(WSL_ARTIFACT)

    assert rig.installs == []
    assert len(rig.dism_calls) == 2


def test_another_wsl_answered_by_msiexec_counts_as_installed(rig):
    rig.products.clear()
    rig.install_answers["wsl.msi"] = 1638

    rig.install(WSL_ARTIFACT)

    assert len(rig.installs) == 1
    assert "podman: another WSL is installed; its msi is not run" in rig.lines


def test_podmans_msi_is_installed_for_every_account_on_wsl(rig):
    rig.install(PODMAN_ARTIFACT)

    assert rig.installs == [
        (
            "podman.msi",
            str(rig.tmp_path / "state" / "podman" / "podman" / "podman.log"),
            ("ALLUSERS=1", "MACHINE_PROVIDER=wsl"),
        )
    ]


@pytest.mark.parametrize("artifact", [PODMAN_ARTIFACT, WSL_ARTIFACT])
def test_an_msi_that_fails_names_its_artifact_and_exit_code(rig, artifact):
    rig.products.clear()
    rig.install_answers[f"{artifact['name']}.msi"] = 1603

    refused = refusal(lambda: rig.install(artifact))

    assert refused.code == "podman_install_failed"
    assert refused.params == {"artifact": artifact["name"], "exit_code": 1603}


def test_an_msi_that_owes_a_restart_writes_the_mark(rig):
    rig.install_answers["podman.msi"] = 3010

    rig.install(PODMAN_ARTIFACT)

    assert rig.applier.is_reboot_pending()


def test_an_artifact_that_is_not_an_msi_is_refused(rig):
    image = {"name": "image", "kind": "tar_zst", "directory": "image"}

    assert refusal(lambda: rig.install(image)).code == "install_failed"
    assert rig.dism_calls == []


# --- the reboot mark across a boot ---


def test_no_mark_owes_no_restart_whatever_servicing_holds(rig):
    rig.is_key = True

    assert not rig.applier.is_reboot_pending()


def test_the_mark_holds_this_boot_and_goes_once_windows_restarted(rig):
    rig.dism_codes["VirtualMachinePlatform"] = 3010
    rig.install(WSL_ARTIFACT)
    rig.boot[0] += 12.5

    assert rig.applier.is_reboot_pending()
    assert rig.make().is_reboot_pending()

    rig.boot[0] += 3600

    assert not rig.applier.is_reboot_pending()
    assert not rig.mark().exists()
    assert not rig.applier.is_reboot_pending()


def test_a_restart_servicing_still_waits_for_keeps_the_mark_after_a_boot(rig):
    rig.dism_codes["Microsoft-Windows-Subsystem-Linux"] = 3010
    rig.install(WSL_ARTIFACT)
    rig.boot[0] += 3600
    rig.is_key = True

    assert rig.applier.is_reboot_pending()

    rig.is_key = False

    assert not rig.applier.is_reboot_pending()
    assert not rig.mark().exists()


def test_a_clock_set_back_is_still_the_same_boot(rig):
    rig.install_answers["podman.msi"] = 3010
    rig.install(PODMAN_ARTIFACT)
    rig.boot[0] -= 600

    assert rig.applier.is_reboot_pending()


def test_a_mark_that_does_not_read_is_forgotten(rig):
    rig.mark().parent.mkdir(parents=True)
    rig.mark().write_text("soon\n")

    assert not rig.applier.is_reboot_pending()
    assert not rig.mark().exists()


# --- the uninstall ---


def test_the_uninstall_removes_podmans_product_alone_and_forgets_the_mark(rig):
    rig.products.append({"code": PODMAN_CODE, "name": "Podman CLI", "version": "6.1.4"})
    rig.mark().parent.mkdir(parents=True)
    rig.mark().write_text("1000000\n")

    rig.applier.uninstall()

    assert rig.uninstalls == [PODMAN_CODE]
    assert not rig.mark().exists()
    assert "podman: uninstalled Podman CLI 6.1.4" in rig.lines


def test_a_product_already_gone_counts_as_uninstalled(rig):
    rig.products.append({"code": PODMAN_CODE, "name": "Podman CLI", "version": "6.1.4"})
    rig.uninstall_answers[PODMAN_CODE] = 1605

    rig.applier.uninstall()

    assert rig.uninstalls == [PODMAN_CODE]


def test_an_uninstall_msiexec_refuses_fails(rig):
    rig.products.append({"code": PODMAN_CODE, "name": "Podman CLI", "version": "6.1.4"})
    rig.uninstall_answers[PODMAN_CODE] = 1603

    assert refusal(rig.applier.uninstall).code == "uninstall_failed"


def test_an_uninstall_with_no_podman_installed_runs_nothing(rig):
    rig.applier.uninstall()

    assert rig.uninstalls == []


# --- the computer's size and the machine's ---


def test_the_host_has_its_processors_and_its_memory_in_whole_gib(rig, monkeypatch):
    monkeypatch.setattr(os, "cpu_count", lambda: 4)

    assert rig.applier.host_facts() == (4, 6)


def test_memory_that_cannot_be_read_is_zero(tmp_path, monkeypatch):
    def unreadable():
        raise OSError("no kernel32")

    monkeypatch.setattr(os, "cpu_count", lambda: None)
    applier = PodmanWindowsApplier(
        platform=Platform(tmp_path), read_memory_bytes=unreadable
    )

    assert applier.host_facts() == (0, 0)


def test_the_disk_is_the_virtual_size_of_the_machines_vhdx(rig):
    disk = rig.home().joinpath(
        ".local", "share", "containers", "podman", "machine", "wsl", "wsldist"
    )
    disk = disk / "podman-machine-default"
    disk.mkdir(parents=True)
    (disk / "ext4.vhdx").write_bytes(vhdx(130 * GIB))

    assert rig.applier.disk_gib(Machine()) == 130
    assert rig.applier.disk_gib(Machine(account="nobody")) == 0

    (disk / "ext4.vhdx").write_bytes(b"vhdxfile" + bytes(64))

    assert rig.applier.disk_gib(Machine()) == 0


def test_a_disk_that_is_not_there_is_zero(rig):
    rig.home()

    assert rig.applier.disk_gib(Machine()) == 0


@pytest.mark.parametrize("head", [b"", b"conectix" + bytes(600000), vhdx(1)[:0x30010]])
def test_a_file_that_is_not_a_vhdx_names_no_size(tmp_path, head):
    path = tmp_path / "disk"
    path.write_bytes(head)

    with open(path, "rb") as stream, pytest.raises(ValueError):
        vhdx_virtual_size(stream)


def test_a_vhdx_reads_its_size_in_bytes(tmp_path):
    path = tmp_path / "disk"
    path.write_bytes(vhdx(100 * GIB + 5))

    with open(path, "rb") as stream:
        assert vhdx_virtual_size(stream) == 100 * GIB + 5


# --- wsl.exe as the account ---


def wsl_lines(machine) -> list:
    """The PowerShell line of each wsl.exe run, with PowerShell's own options checked."""
    lines = []
    for run in machine.runs:
        assert run[:-1] == [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
        ]
        lines.append(run[-1])
    return lines


def test_wsl_runs_through_powershell_with_its_options_as_bare_words():
    line = wsl_script(
        "C:\\Windows\\System32\\wsl.exe",
        ["--manage", "podman-machine-default", "--resize", "120GB"],
    )

    assert line == (
        "$env:WSL_UTF8 = '1'; & 'C:\\Windows\\System32\\wsl.exe' '--manage' "
        "'podman-machine-default' '--resize' '120GB'; exit $LASTEXITCODE"
    )


def test_a_halt_shuts_wsl_down_as_the_account(rig):
    machine = Machine()

    rig.applier.halt(machine)

    assert wsl_lines(machine) == [
        "$env:WSL_UTF8 = '1'; & 'C:\\Windows\\System32\\wsl.exe' '--shutdown'; "
        "exit $LASTEXITCODE"
    ]


def test_wsls_own_words_come_back_with_a_refusal(rig):
    machine = Machine(answers=[(1, "The operation timed out.\r\n")])

    refused = refusal(lambda: rig.applier.halt(machine))

    assert refused.code == "machine_set_failed"
    assert refused.params == {"detail": "The operation timed out."}


def test_a_wsl_that_cannot_run_is_machine_set_failed(rig):
    machine = Machine(answers=[OSError("no task")])

    assert refusal(lambda: rig.applier.halt(machine)).code == "machine_set_failed"


def test_a_resize_shuts_wsl_down_then_sizes_the_machines_disk(rig):
    machine = Machine()

    rig.applier.resize_disk(machine, disk_gib=120)

    assert [line.split("; ")[1] for line in wsl_lines(machine)] == [
        "& 'C:\\Windows\\System32\\wsl.exe' '--shutdown'",
        "& 'C:\\Windows\\System32\\wsl.exe' '--manage' 'podman-machine-default' "
        "'--resize' '120GB'",
    ]
    assert "podman: the disk of lab's machine is 120 GB" in rig.lines


@pytest.mark.parametrize(
    "answers, said",
    [
        ([(1, "Access is denied.")], "Access is denied."),
        ([(0, ""), (1, "The disk is in use.")], "The disk is in use."),
        ([(0, ""), (5, "")], "wsl --manage exited 5"),
    ],
)
def test_a_size_wsl_refuses_is_machine_set_failed(rig, answers, said):
    machine = Machine(answers=answers)

    refused = refusal(lambda: rig.applier.resize_disk(machine, disk_gib=120))

    assert refused.code == "machine_set_failed"
    assert refused.params == {"detail": said}


# --- the account's .wslconfig ---


def test_the_resources_are_written_into_the_accounts_wslconfig_as_the_account(rig):
    machine = Machine()
    rig.home()

    rig.applier.write_resources(machine, cpus=2, memory_gib=4)

    path = rig.tmp_path / "Users" / "lab" / ".wslconfig"
    assert path.read_bytes() == b"[wsl2]\r\nprocessors=2\r\nmemory=4GB\r\n"
    assert machine.steps == [("lab", "_merge_wslconfig")]


def test_a_wslconfig_keeps_its_other_lines_and_its_byte_order_mark(rig):
    path = rig.home() / ".wslconfig"
    path.write_bytes(
        b"\xef\xbb\xbf# mine\n[wsl2]\nProcessors = 8\nswap=0\n\n[experimental]\nx=1\n"
    )

    rig.applier.write_resources(Machine(), cpus=2, memory_gib=3)

    assert path.read_bytes() == (
        b"\xef\xbb\xbf# mine\n[wsl2]\nprocessors=2\nswap=0\nmemory=3GB\n\n"
        b"[experimental]\nx=1\n"
    )


def test_an_unchanged_wslconfig_is_not_written(rig):
    path = rig.home() / ".wslconfig"
    path.write_bytes(b"[wsl2]\r\nprocessors=2\r\nmemory=4GB\r\n")
    os.utime(path, (1, 1))

    rig.applier.write_resources(Machine(), cpus=2, memory_gib=4)

    assert path.stat().st_mtime == 1
    assert rig.lines == []


def test_an_account_without_a_home_cannot_be_given_resources(rig):
    refused = refusal(
        lambda: rig.applier.write_resources(
            Machine(account="nobody"), cpus=1, memory_gib=1
        )
    )

    assert refused.code == "machine_set_failed"


@pytest.mark.parametrize(
    "before, after",
    [
        ("", "[wsl2]\r\nprocessors=2\r\nmemory=4GB\r\n"),
        (
            "[boot]\nsystemd=true",
            "[boot]\nsystemd=true\n\n[wsl2]\nprocessors=2\nmemory=4GB\n",
        ),
        (
            "[wsl2]\r\nmemory=8GB\r\n; processors=16\r\nkernel=C:\\\\k\r\n",
            "[wsl2]\r\nmemory=4GB\r\n; processors=16\r\nkernel=C:\\\\k\r\n"
            "processors=2\r\n",
        ),
        (
            "[WSL2]\nprocessors=1\nmemory=1GB\n[other]\nmemory=9GB\n",
            "[WSL2]\nprocessors=2\nmemory=4GB\n[other]\nmemory=9GB\n",
        ),
        ("[wsl2]\nswap=0", "[wsl2]\nswap=0\nprocessors=2\nmemory=4GB\n"),
    ],
)
def test_the_merge_sets_two_keys_under_wsl2_and_keeps_every_other_line(before, after):
    assert merged_wslconfig(before, processors=2, memory_gib=4) == after


@pytest.mark.parametrize(
    "text, numbers",
    [("3.0.3.0", (3, 0, 3, 0)), ("2.6.1", (2, 6, 1)), ("", (0,)), ("3.1-rc", (3, 1))],
)
def test_a_version_reads_as_numbers(text, numbers):
    assert version_numbers(text) == numbers

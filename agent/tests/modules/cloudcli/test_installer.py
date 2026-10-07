"""Putting Node.js on the machine and building an account's install.

What these pin: a tarball or a zip with one Node.js directory lands whole
under the module's root, read-only, replacing the one before; an archive
that is not one, or that names a path outside it, is
``cloudcli_node_download_failed``; npm runs with its cache inside the app
directory and an empty file as the account's configuration; a failure
naming a native module is that module's, any other npm's; and an
instance's environment is written from scratch, its ``PATH`` listing Node's
directory, the account's usual command directories and the system's on
each system, naming no tool.
"""

import io
import ntpath
import os
import stat
import tarfile
import zipfile

import pytest

from neutrino_agent.exceptions import ModuleApplyError
from neutrino_agent.modules.cloudcli import installer
from neutrino_agent.modules.cloudcli.config import CloudcliConfig, jwt_secret

NODE = "node-v22.23.3-linux-x64"


def tarball(path, top=NODE, extra=()):
    with tarfile.open(path, "w:gz") as archive:
        for name, data in [(f"{top}/bin/node", b"#!node"), *extra]:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mode = 0o755
            archive.addfile(info, io.BytesIO(data))
        link = tarfile.TarInfo(f"{top}/bin/npm")
        link.type = tarfile.SYMTYPE
        link.linkname = "../lib/node_modules/npm/bin/npm-cli.js"
        archive.addfile(link)
    return str(path)


def test_a_tarball_lands_whole_and_read_only(tmp_path):
    root = tmp_path / "cloudcli"

    directory = installer.unpack_node(
        tarball(tmp_path / "node.tar.gz"), package_kind="tar", root=str(root)
    )

    assert directory == str(root / NODE)
    assert installer.node_dir(str(root)) == directory
    node = installer.node_path(directory, "linux")
    assert open(node, "rb").read() == b"#!node"
    assert stat.S_IMODE(os.stat(node).st_mode) & 0o222 == 0
    assert os.readlink(os.path.join(directory, "bin", "npm")).endswith("npm-cli.js")
    assert [name for name in os.listdir(root) if not name.startswith(NODE)] == []


def test_a_new_node_replaces_the_one_before(tmp_path):
    root = tmp_path / "cloudcli"
    installer.unpack_node(
        tarball(tmp_path / "a.tar.gz"), package_kind="tar", root=str(root)
    )

    installer.unpack_node(
        tarball(tmp_path / "b.tar.gz", top="node-v22.24.0-linux-x64"),
        package_kind="tar",
        root=str(root),
    )

    assert os.listdir(root) == ["node-v22.24.0-linux-x64"]


def test_a_zip_lands_the_same(tmp_path):
    path = tmp_path / "node.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("node-v22.23.3-win-x64/node.exe", b"MZ")

    directory = installer.unpack_node(
        str(path), package_kind="zip", root=str(tmp_path / "cloudcli")
    )

    assert os.path.isfile(os.path.join(directory, "node.exe"))


@pytest.mark.parametrize("kind", ["tar", "zip", "msi"])
def test_an_archive_that_is_not_one_is_a_failed_node_download(tmp_path, kind):
    path = tmp_path / "junk"
    path.write_bytes(b"<html>")

    with pytest.raises(ModuleApplyError) as caught:
        installer.unpack_node(str(path), package_kind=kind, root=str(tmp_path / "c"))

    assert caught.value.code == "cloudcli_node_download_failed"


def test_an_archive_without_one_node_directory_is_refused(tmp_path):
    path = tarball(tmp_path / "x.tar.gz", top="something")

    with pytest.raises(ModuleApplyError) as caught:
        installer.unpack_node(path, package_kind="tar", root=str(tmp_path / "c"))

    assert caught.value.code == "cloudcli_node_download_failed"


def test_a_member_outside_the_archive_is_refused(tmp_path):
    path = tarball(tmp_path / "x.tar.gz", extra=[("../escape", b"x")])

    with pytest.raises(ModuleApplyError):
        installer.unpack_node(path, package_kind="tar", root=str(tmp_path / "c"))

    assert not (tmp_path / "escape").exists()


def test_removing_the_module_takes_the_read_only_tree(tmp_path):
    root = tmp_path / "cloudcli"
    installer.unpack_node(
        tarball(tmp_path / "a.tar.gz"), package_kind="tar", root=str(root)
    )

    installer.remove_node(str(root))

    assert not root.exists()


def test_npm_installs_from_the_registry_the_state_names():
    """A mainland hub names npmmirror; with none named npm keeps its own."""
    app = "/home/ann/.local/share/neutrino/agent/cloudcli/app"

    named = installer.npm_environment(app, registry="https://registry.npmmirror.com")

    assert named["npm_config_registry"] == "https://registry.npmmirror.com"
    assert "npm_config_registry" not in installer.npm_environment(app)


def test_npm_keeps_to_the_app_directory():
    app = "/home/ann/.local/share/neutrino/agent/cloudcli/app"

    assert installer.npm_environment(app)["npm_config_cache"] == app + "/.npm"
    assert installer.npm_environment(app)["npm_config_userconfig"] == app + "/.npmrc"
    assert installer.npm_arguments(app) == [
        "install",
        "@cloudcli-ai/cloudcli@1.37.3",
        "--prefix",
        app,
    ]
    assert installer.app_dir("/home/ann", "linux") == app
    assert installer.server_path(app).endswith(
        "app/node_modules/@cloudcli-ai/cloudcli/dist-server/server/index.js"
    )


@pytest.mark.parametrize(
    "output, expected",
    [
        (
            "prebuild-install warn install No prebuilt binaries found\n"
            "gyp ERR! build error\nnpm error path .../node_modules/node-pty",
            (
                "cloudcli_native_module_failed",
                {
                    "account": "ann",
                    "module": "node-pty",
                    "detail": "prebuild-install warn install No prebuilt binaries "
                    "found | gyp ERR! build error | npm error path "
                    ".../node_modules/node-pty",
                },
            ),
        ),
        (
            "npm error code ETIMEDOUT\nnpm error network request failed",
            (
                "cloudcli_npm_install_failed",
                {
                    "account": "ann",
                    "detail": "npm error code ETIMEDOUT | npm error network "
                    "request failed",
                },
            ),
        ),
    ],
)
def test_a_failed_install_names_its_step(output, expected):
    failure = installer.npm_failure(output, "ann")

    assert (failure.code, failure.params) == expected


def test_the_installed_version_is_read_from_the_package(tmp_path):
    app = tmp_path / "app"
    package = app / "node_modules" / "@cloudcli-ai" / "cloudcli"
    package.mkdir(parents=True)
    (package / "package.json").write_text('{"version": "1.37.3"}')

    assert installer.installed_version(str(app)) == "1.37.3"
    assert installer.installed_version(str(tmp_path / "none")) == ""


def test_an_instance_runs_with_an_environment_written_from_scratch_naming_no_gateway():
    config = CloudcliConfig.from_dict(
        {
            "gateway_url": "http://10.0.0.1:8317",
            "gateway_key": "k",
            "instances": [{"account": "ann", "port": 3001, "token_secret": "s"}],
        }
    )

    environment = installer.service_environment(
        config.instances[0],
        upstream_port=41234,
        home="/home/ann",
        os_name="linux",
        node_dir="/var/lib/neutrino/agent/cloudcli/n/bin",
    )

    assert environment == {
        "HOST": "127.0.0.1",
        "SERVER_PORT": "41234",
        "JWT_SECRET": jwt_secret("s"),
        "DATABASE_PATH": "/home/ann/.local/share/neutrino/agent/cloudcli/auth.db",
        "HOME": "/home/ann",
        "PATH": "/var/lib/neutrino/agent/cloudcli/n/bin:/home/ann/.local/bin:"
        "/home/ann/bin:/usr/local/bin:/usr/bin:/bin",
    }


def test_a_mac_instance_lists_homebrew_before_the_system_s_directories():
    config = CloudcliConfig.from_dict(
        {"instances": [{"account": "ann", "port": 3001, "token_secret": "s"}]}
    )

    environment = installer.service_environment(
        config.instances[0],
        upstream_port=41234,
        home="/Users/ann",
        os_name="darwin",
        node_dir="/Library/Application Support/Neutrino/agent/state/cloudcli/n/bin",
    )

    assert environment["PATH"].split(":") == [
        "/Library/Application Support/Neutrino/agent/state/cloudcli/n/bin",
        "/Users/ann/.local/bin",
        "/Users/ann/bin",
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
    ]
    assert environment["HOME"] == "/Users/ann"
    assert not [name for name in environment if "CLAUDE" in name]


def test_a_windows_instance_puts_node_and_npm_before_the_account_s_own_path():
    config = CloudcliConfig.from_dict(
        {"instances": [{"account": "ann", "port": 3001, "token_secret": "s"}]}
    )

    environment = installer.service_environment(
        config.instances[0],
        upstream_port=41234,
        home="C:\\Users\\ann",
        os_name="windows",
        node_dir="C:\\ProgramData\\Neutrino\\agent\\state\\cloudcli\\n",
        join=ntpath.join,
    )

    assert environment["PATH"] == (
        "C:\\ProgramData\\Neutrino\\agent\\state\\cloudcli\\n;%APPDATA%\\npm;%PATH%"
    )
    assert "HOME" not in environment


def test_an_app_is_ready_with_the_pinned_package_and_every_native_module(tmp_path):
    app = tmp_path / "app"
    package = app / "node_modules" / "@cloudcli-ai" / "cloudcli"
    package.mkdir(parents=True)
    (package / "package.json").write_text('{"version": "1.37.3"}')
    for name in ("better-sqlite3", "node-pty"):
        (app / "node_modules" / name).mkdir()
        (app / "node_modules" / name / "package.json").write_text("{}")

    assert installer.is_app_ready(str(app)) is False
    (package / "node_modules" / "bcrypt").mkdir(parents=True)
    (package / "node_modules" / "bcrypt" / "package.json").write_text("{}")
    assert installer.is_app_ready(str(app)) is True
    (package / "package.json").write_text('{"version": "1.37.2"}')
    assert installer.is_app_ready(str(app)) is False


def test_the_editions_npm_settings_join_the_environment_and_never_replace_it():
    app = "/home/ann/app"

    held = installer.npm_environment(
        app,
        registry="https://registry.npmmirror.com",
        extra={
            "npm_config_better_sqlite3_binary_host": "https://m.example/bs3",
            "npm_config_cache": "/elsewhere",
        },
    )

    assert held["npm_config_better_sqlite3_binary_host"] == "https://m.example/bs3"
    assert held["npm_config_cache"] == app + "/.npm"


def test_a_failure_keeps_the_tools_last_words():
    output = "\n".join(
        [
            "added 1 package",
            "prebuild-install warn install Request timed out",
            "gyp info it worked if it ends with ok",
            "gyp ERR! stack Error: not found: make",
            "npm error code 1",
        ]
    )

    assert installer.failure_detail(output) == (
        "prebuild-install warn install Request timed out | gyp ERR! stack Error: "
        "not found: make | npm error code 1"
    )
    assert installer.failure_detail("just one line") == "just one line"


def test_the_install_line_names_the_registry_host():
    assert installer.registry_host("https://registry.npmmirror.com") == (
        "registry.npmmirror.com"
    )
    assert installer.registry_host("") == "registry.npmjs.org"


def test_the_environment_names_the_database_file_an_instance_runs_on():
    from neutrino_agent.modules.cloudcli import installer as installer_module
    from neutrino_agent.modules.cloudcli.config import CloudcliInstance

    instance = CloudcliInstance(
        account="ann", port=3001, web_password="p", token_secret="s"
    )

    plain = installer_module.service_environment(
        instance, upstream_port=41000, home="/home/ann", os_name="linux"
    )
    fresh = installer_module.service_environment(
        instance,
        upstream_port=41000,
        home="/home/ann",
        os_name="linux",
        database_name="auth-20261006T120000Z.db",
    )

    assert plain["DATABASE_PATH"].endswith("/cloudcli/auth.db")
    assert fresh["DATABASE_PATH"].endswith("/cloudcli/auth-20261006T120000Z.db")

# Supported platforms

Every Neutrino Hub package is 64-bit, and there is no 32-bit build. The hub, the agent and the client install on Linux, Windows and macOS, and phones have the client only.

## Hub, agent, client

Find the row of your system. The last three columns show the package type to download.

| System                                                              | Architecture  | Hub            | Agent          | Client                                                   |
| ------------------------------------------------------------------- | ------------- | -------------- | -------------- | -------------------------------------------------------- |
| Debian 12 and later, Ubuntu 22.04 and later, Raspberry Pi OS 64-bit | x86-64, ARM64 | `.deb`         | `.deb`         | `.deb`                                                   |
| RHEL 9 family (AlmaLinux, Rocky), Fedora                            | x86-64, ARM64 | `.rpm`         | `.rpm`         | `.rpm`                                                   |
| Arch, EndeavourOS, Manjaro                                          | x86-64        | `.pkg.tar.zst` | `.pkg.tar.zst` | `.pkg.tar.zst`                                           |
| Windows 10 1809 and later, Windows 11                               | x86-64        | `.msi`         | `.msi`         | `.msi`                                                   |
| macOS 13 and later, Apple silicon                                   | ARM64         | `.pkg`         | `.pkg`         | `.pkg`                                                   |
| macOS 13 and later, Intel                                           | x86-64        | `.pkg`         | `.pkg`         | `.pkg`                                                   |
| Android 8.0 and later                                               | arm64-v8a     | None           | None           | `.apk`                                                   |
| iOS 16 and later                                                    | arm64         | None           | None           | `.ipa`, unsigned; you sign it yourself before installing |

Linux packages require glibc 2.34 or later. The RHEL 9 family must have EPEL enabled first, and the install script enables it automatically; Fedora skips this step. On Linux, the client needs a desktop session to run.

The Windows build is x86-64 only, and RustDesk and cc-switch have no ARM64 build either.

When hub setup finishes, an agent is also installed on the same system, on Arch as well.

The files in the table and `SHA256SUMS` are published under the same release tag.

## Accounts the programs run as

The hub and the agent run as administrator, and the client runs as your own account.

| Program    | Linux            | macOS              | Windows          |
| ---------- | ---------------- | ------------------ | ---------------- |
| Hub, agent | root             | root, LaunchDaemon | SYSTEM           |
| Client     | Your own account | Your own account   | Your own account |

The agent has no window. On a phone, the client is the app itself.

## Version compatibility

0.6 works only with 0.6. A 0.5 agent or client that connects to a 0.6 hub gets no response at all. Reinstall it, then join with a new link. See [Upgrade from 0.5](/en/hub/upgrade).

## Network modes

Server mode exists on all three systems. Router and side gateway exist on Linux only.

| Mode                              | Linux | Windows | macOS |
| --------------------------------- | ----- | ------- | ----- |
| Server                            | Yes   | Yes     | Yes   |
| Router (including one-arm router) | Yes   | No      | No    |
| Side gateway                      | Yes   | No      | No    |

The editions each mode supports are in [Network shapes: server, router, side gateway](/en/hub/network).

## Apps

An app that a system cannot run appears grey in the **Add module** dialog.

| App            | Linux                                    | Windows                     | macOS                 | Other requirements                                                                 |
| -------------- | ---------------------------------------- | --------------------------- | --------------------- | ---------------------------------------------------------------------------------- |
| Remote desktop | Yes                                      | Yes                         | Yes                   | Included with the agent                                                            |
| File share     | Debian, RHEL and Arch families           | Built into the system       | Built into the system | On Linux, the system's Samba 4.15 or later                                         |
| Terminal       | Yes                                      | Yes                         | Yes                   | Included with the agent                                                            |
| SSH server     | amd64, arm64                             | amd64                       | Apple silicon, Intel  | Included with the agent                                                            |
| VS Code        | amd64, arm64                             | amd64                       | Apple silicon, Intel  | You must accept Microsoft's terms first                                            |
| code-server    | amd64, arm64                             | None                        | Apple silicon, Intel  |                                                                                    |
| Gitea          | amd64, arm64                             | amd64                       | Apple silicon, Intel  | On Windows and macOS, you install git 2.0 or later yourself                        |
| CloudCLI       | amd64, arm64                             | amd64                       | Apple silicon, Intel  | Includes Claude Code. Turning on **AI tools use the hub's gateway** is recommended |
| Codeg          | amd64, arm64                             | amd64                       | Apple silicon, Intel  |                                                                                    |
| Hermes WebUI   | Every system that can run **Containers** | amd64                       | Apple silicon, Intel  | Requires **Containers**, with 1 GiB of memory recommended                          |
| Ayakaleaf      | Every system that can run **Containers** | amd64                       | Apple silicon, Intel  | Requires **Containers**, with 3 GiB of memory recommended                          |
| SiYuan         | amd64, arm64                             | amd64                       | Apple silicon, Intel  |                                                                                    |
| Claude Code    | amd64, arm64                             | amd64, arm64                | Apple silicon, Intel  | A regular program that runs in a terminal                                          |
| Codex          | amd64, arm64                             | amd64, arm64                | Apple silicon, Intel  | A regular program that runs in a terminal                                          |
| Containers     | Debian, RHEL and Arch families           | amd64, build 19041 or later | 13 or later           | On Linux, the system's Podman 3.4 or later                                         |

A Linux system outside these three families, such as Alpine, has no containers, so it cannot run Hermes WebUI or Ayakaleaf either.

On Windows, containers are tested on build 26100 only, and 19041 is the lowest build the installer accepts.

**AI tools use the hub's gateway** uses cc-switch and supports the same systems and architectures as the SSH server.

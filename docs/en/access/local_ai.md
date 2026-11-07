# Let local AI tools operate your systems

AI tools such as Claude Code on your computer can operate each of your systems by running commands, with no extra setup.

AI tools run commands in a terminal, so they can use [Terminal commands](/en/access/terminal) and [SSH connections](/en/access/ssh) directly. Exit codes return unchanged, so an AI tool can tell whether a command succeeded.

## Prerequisites

These commands go through the desktop client, so the client must keep running:

- `nclient terminal exec` needs the **Terminals** permission, and that system's **Terminal** tab must have an account enabled.
- `ssh` and `rsync` need the **SSH** permission and the switch that [SSH connections](/en/access/ssh) turns on. `rsync` must be installed on both ends.

## Tell the AI tool about your systems

In `CLAUDE.md` or `AGENTS.md`, write each system's name and purpose, for example:

```markdown
- my-computer: desktop for writing code
- lab-gpu: GPU computer for running experiments; connect with `ssh lab-gpu.nt`
```

## Commands the AI tool can use

```bash
# Run a command on another system; the exit code returns unchanged
nclient terminal exec lab-gpu -- nvidia-smi
ssh lab-gpu.nt nvidia-smi
# Transfer files, list systems, use an app by its name
rsync -a data/ lab-gpu.nt:data/
nclient ssh list
nclient app use <app>
```

`nclient app use` prints the app's local address, and the AI tool connects to the app at that address.

Exit codes return unchanged. The following command exits with 7 on the remote system, and the local exit code is 7 as well.

```bash
nclient terminal exec my-computer -- sh -c "exit 7"
echo $?
```

```text
7
```

## Limit what the AI tool can do

An AI tool can do anything the account can do, so limit it with permissions.

On the panel's **Clients** page, give this computer permissions of its own, and select only the systems it needs. You can also open terminals and keep files closed, or the reverse, as [Clients](/en/hub/clients) describes.

To open AI sessions on other systems, use [CloudCLI](/en/deploy/cloudcli).

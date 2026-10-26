# The machine's AI tools

The `ai_tools` section of the state says which of the machine's accounts
point their AI tools at the hub's gateway, and with which models
([protocol.md](../protocol.md), "The sections"). It is a setting, not a
module: nothing is installed, started or stopped, and it has no `want`. The agent makes it true and reports each
account's result in the `ai_tools` section of its report.

The accounts are the hub's word: every available account whose switch,
**AI tools use the hub's gateway** in the account's form on the machine page,
is on, each with its own model choices ([agent.md](../agent.md), "The two
layers and the accounts"). The agent looks nothing up and adds no account of
its own. Codeg's Claude Code and
Codex entries are the ACP adapters `claude-agent-acp` and `codex-acp`, which
read the account's `~/.claude/settings.json` and `~/.codex/config.toml`, the
files cc-switch writes, so the setting covers Codeg's sessions as well
([modules/codeg.md](modules/codeg.md)).

For each account the state names, the agent runs the client's steps as that
account with the account's own `tool_configs`, with the copy of cc-switch the agent fetched
from the hub ([hub_components/ai.md](../hub_components/ai.md), "How a client
points its tools at the gateway", and "How a managed machine's tools are
pointed at the gateway" for what differs). An account whose records already
carry the wanted settings is not run again. An account is switched back by
the same steps as the client's deactivation:

- when its switch goes off, so the state names it no longer, or when the
  whole section turns off;
- by `nagent service uninstall`, once the agent's service has stopped and
  before anything is removed;
- on `nagent leave`, and when a refusal of `binding_unknown` ends the
  binding ([agent.md](../agent.md), "What a refusal means to the agent").

**The tools reach the gateway through the agent.** The gateway answers on
the hub's loopback alone, so while the section is on the agent listens on
`127.0.0.1:8317`, the AI gateway forward, and relays each connection made
there to the hub over its channel ([agent.md](../agent.md), "The AI gateway
forward"). The forward is also open while a container module that uses the
gateway is installed, for that module's own key. The endpoint the switch writes into each tool is that port. A
tool reaches the gateway while the agent runs and its channel to the hub is
up. On the hub's own machine the agent opens no forward, and the endpoint is
the gateway's own loopback port.

`nagent leave` and `nagent service uninstall` print one line per account
they switched back, `ai tools   <account>: <state> <code>`, and the agent
package's removal on Linux shows what both print.

**cc-switch comes from the hub when it is needed.** The agent's package
does not carry it. While the section is on and names an account, the agent
needs a copy of the version the section's `cc_switch_version` names. When it
has none, or one of another version, it opens `package {module: cc_switch,
artifact, digest}` with the section's `cc_switch_artifact`
([protocol.md](../protocol.md), "The stream layer"), checks the bytes
against the digest, unpacks the `cc-switch` at the
archive's top
(`cc-switch.exe` on Windows) into `ai_tools/bin/` under the state root, and
writes the version beside it in `version`, replacing a copy of another
version whole. The directory is root's own: every account may read and run
what is in it and none may write it, as with any software the hub sends
([agent.md](../agent.md), "The platform layer"). A switch back while the
section is off runs whatever copy is there, and fetches the version the
section names when none is. The hub's cache fetches cc-switch from its
publisher's GitHub release and from the release sites, which hold the same
files ([module_install.md](module_install.md), "Sources"). A download or an
unpack that fails gives every account the section names, and every account
it is to switch back, `failed` with `download_failed {file, sources}`, and a
section with no `cc_switch_artifact` with `no_platform_build {module}`; it
runs nothing, and leaves the state to be tried again at the next state or the
next retry.

The records are the client's, one per tool, `{is_present, previous, added}`,
kept under the state root in `ai_tools/<account>/<tool>.json`, root's own,
never in the account's home. An account whose records are all gone after
a switch back has its directory removed.

**cc-switch runs on a store of the agent's own.** Every cc-switch the agent
starts for an account has `CC_SWITCH_CONFIG_DIR` set to `cc_switch` beside
the payload in the account's Neutrino tree
(`~/.local/share/neutrino/agent/ai_tools/cc_switch` on Linux,
`~/Library/Application Support/Neutrino/agent/ai_tools/cc_switch` on macOS,
`%LOCALAPPDATA%\Neutrino\agent\ai_tools\cc_switch` on Windows), made as
the account, mode 700, which cc-switch requires of a store it is pointed at.
The account's own `~/.cc-switch`, and the CC Switch app that keeps its store
there, are never read or written. A tool's record says `is_own_store`; a
tool switched before this store existed is switched back in
`~/.cc-switch`, where it was switched. The switch back of every tool
removes the store as the account, and with it each directory of the tree
left empty.

**The account's own files come back byte for byte.** Before a tool's first
switch, its record also keeps `is_dir_present`, whether the tool's
directory was there, and `kept`, the text of every file a switch may write
in it, read as the account, or null for one that was absent: Claude Code's
`~/.claude/settings.json`, Codex's `~/.codex/config.toml` and `auth.json`,
and Gemini's `~/.gemini/.env` and `settings.json`. cc-switch writes a tool's
files only into a directory that is there, so a switch makes the directory,
as the account, for a tool that has none, and every tool the log names as
switched has its files written and read back naming the hub. cc-switch
writes them with the account's own file mask, so once it has run, every file
that holds the gateway key, Claude Code's `settings.json`, Codex's
`auth.json` and Gemini's `.env`, is set to mode 600 as the account, and the
record keeps `kept_modes`, each kept file's own mode; on Windows a profile's
files are its owner's by their access list and no mode is set or kept. The
switch back, once cc-switch has switched away and deleted the hub's
provider, writes each kept file back as it was with its own mode, takes
away each that was absent, and takes away a directory the switch made once
it is empty. A switch back that
cannot run cc-switch, or cannot read its list of providers, is the
account's `failed` with `switch_failed {account, detail}`, and the records,
with the kept files, stay for the next try.

Each account's switch or switch back holds that account's lock from its
first step to its last: the file `ai_tools/.locks/<account>` under the state
root, locked with `flock` on Linux and macOS and `msvcrt.locking` on
Windows, so the service and a `nagent leave` or `nagent service uninstall`
never run cc-switch for one account at once, nor replace each other's
one-shot task on Windows. A run that finds the lock held waits up to five
minutes and then fails as `switch_failed` with the detail `another run holds
the account`, and since the system frees a lock when its process ends, a
file a killed process left behind blocks no one. Holding the lock, the agent
makes no switch once the machine has no binding: `nagent leave` and a
`binding_unknown` refusal remove the binding before they switch back, so a
service that waited on the lock finds none and switches nothing.

**Every step in an account's home runs as that account, reads included.**
cc-switch runs as the account, with the account's home and its own
environment ("Running as an account" in the platform table,
[agent.md](../agent.md), "The platform layer"), and so does each file step of
the client's sequence: reading a tool's file, writing Codex's effort into
`config.toml`, removing a file cc-switch made. An account can replace any
file in its home with a link to a file only root reads, so a read made as
root would hand that file to cc-switch and through it back to the account. On
Linux and macOS the file steps are `cat`, `test -f`, `sh -c` writing what
arrives on standard input, and `rm -f`. On Windows the agent reads a file, or
checks that one exists, in its own process while it impersonates the
account's login from `LogonUserW`. A write, a directory made and a removal there run the same way,
in the agent's own process while it impersonates the account.

`config common extract` and `config common set` read their input from a
file. The agent writes that input as the account to `payload` in the
account's own tree, `~/.local/share/neutrino/agent/ai_tools/` on Linux,
`~/Library/Application Support/Neutrino/agent/ai_tools/` on macOS and
`%LOCALAPPDATA%\Neutrino\agent\ai_tools\` on Windows, making the
directories it lacks. It runs the one cc-switch call that reads the file,
and straight after removes it as the account, then each of `ai_tools`,
`agent` and the Neutrino directory that is left empty, in that order, so an
account that had no Neutrino tree has none afterwards. The file holds a
tool's live configuration in the shape `extract` reads, or the shared
settings `set` stores ([files.md](../files.md), "One root, three names").

**The delete is answered on a terminal.** `provider delete` prints `(y/N)`
and reads the reply from its terminal; with a pipe on its standard input it
exits with `The input device is not a TTY`, and no flag stands in for the
reply. On Linux and macOS the agent makes a pseudo-terminal itself, starts
cc-switch on it as the account, and types `y` and Enter once the prompt
shows. On Windows the agent reaches an account only through a scheduled
task, so the terminal is made inside that task: the task runs
`nagent answer --prompt "(y/N)" --answer y -- <cc-switch> --app <tool>
provider delete neutrino`, `<cc-switch>` being the path of the agent's own
cc-switch and `<tool>` the tool, and the agent's own program makes a pseudo
console there, starts cc-switch on it, types the reply, and prints what the
console drew.

On macOS a program is put in an account's GUI session as the account by
`launchctl asuser <uid> <nagent> step-down --uid <uid> --gid <gid> --
<program>`: `launchctl` starts the agent's own program in the session, and
`step-down` sets the account's group as its only supplementary group, then
its group, then its user, and replaces itself with the program. It opens
no socket and reads no state. `chroot -u` is not used: macOS kills a
program with the hardened runtime under it. A command that does not start,
or exits other than 0, leaves one line in the agent's log.

`answer` is the one `nagent` verb any account may run. It starts the
program it is given as the account that runs it, with that account's
rights and no other; it reads no binding, opens neither the control socket
nor a socket to the hub, and changes nothing the account could not change by
running the program itself.

**Windows keeps the login until the switch back.** A task runs as an account
only with the account's password, and the state carries each account's login
only while the section is on. The agent therefore keeps the login an account
was switched with in `ai_tools/<account>/login.json` under the state root,
readable by SYSTEM and the administrators alone as everything under
`%ProgramData%\Neutrino\agent` is ([files.md](../files.md)), and deletes it with
the account's records. Every switch back reads it from there: after the
section turns off, after the account leaves the list, at an uninstall, at a
leave.

The report names each account the state names and each one switched back
under the current state's hash, `{account, state, code, params,
has_records}`, `state` being `switched`, `switched_back` or `failed`, and
`has_records` whether the agent keeps the account's records at the moment
of the report: a tool of it still pointed at the hub, whose original files
wait to be written back. A failure carries the client's
code where it fits, `switch_failed {account, detail}`, the download's
`download_failed {file, sources}`, and the module codes for an account it
cannot run as:
`account_unknown {account}`, and on Windows `credential_missing {account}`
and `credential_invalid {account}`. A failed account is not tried again
while the state's hash is unchanged, as a failed module is not.

After the agent restarts it reports each account whose records stand as
`switched` until a new state arrives, and acts on no state whose hash it
already tried, so a restart of the same build switches nothing and
switches nothing back.

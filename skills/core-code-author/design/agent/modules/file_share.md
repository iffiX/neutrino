# The File share module

The `samba` module is the file share: Samba on Linux, and the system's own
SMB server on Windows and macOS ([agent.md](../../agent.md), "Which modules
each system runs"). It runs beside what the person set up and manages only
the users and the shares it made itself ([agent.md](../../agent.md),
"Parallel, never take over").

Its one setting is its enabled accounts. For each it serves one share, named
after the account, at the account's share path, to one SMB user,
`neutrino-<account>`, with a password the hub generates
([agent.md](../../agent.md), "The file share's accounts"); the module keeps
no share list and no user list of its own, and a client mounts a share with
the user and the password the `service` frame hands it. Beside the accounts'
shares it serves the shares the hub's `samba.json` names itself, a ZFS
dataset's and a share a 0.5 hub carried over, each open to the enabled
accounts' SMB users it names. A Samba a person set up by hand reads
`installed` or `running` and is adopted as the module with an empty
configuration: its shares and its users stay the person's, the hub copies
none of them, and the panel does not manage them.

## Linux

The module's shares live in a file of the module's own,
`/etc/samba/neutrino.conf`, whose first line is the module's generated
marker. `smb.conf` is the person's, whoever wrote it, an earlier version of
this module included: a file an earlier version rendered whole, its first
line the marker, is the person's file now, left as it is. While the module
serves at least one share of its own it adds one line to `smb.conf`,
`include = /etc/samba/neutrino.conf`, right after the `[global]` header,
once, and changes nothing else in it, not its `[global]`, not the person's
shares, not the person's Samba users. When the last share of the module's
goes, at a disable as at uninstall, the module deletes its file and takes
that one line out again; a machine adopted with no enabled account keeps
its `smb.conf` byte for byte, and the module starts no server there. A
machine with no `smb.conf` at all gets the distribution's stock file first,
the first of `/usr/share/samba/smb.conf`, `/etc/samba/smb.conf.example` and
`/usr/share/doc/samba-common/examples/smb.conf.default` that is there, else
a `[global]` of one line, `server role = standalone server`. The apply's
note says which. The stock file's settings reach none of the module's
users: `unix password sync` acts only on a password change made through
SMB, the module's users never make one, the printer shares and `[homes]`
serve nothing to a user with no home and no login shell, and `map to guest
= bad user` reaches no share whose `valid users` names one user.

What a hub of 0.5 had the module make, its shares and its Samba logins, is
the person's own after the upgrade: the hub's move of the 0.5 files drops
them from `samba.json`, so the hub neither carries nor manages them, and
the machine goes on serving them as they are, to the logins they had. A
0.5 share named after an account then refuses that account's share with
`share_name_taken {name}`, as any share of the person's does, until the
person renames or removes it. The ports a hub of 0.5 kept for VS Code,
code-server and CloudCLI are not carried either; the agent takes fresh
ones ([../../protocol.md](../../protocol.md), "The account layer in the
state").

Everything named `neutrino-` is the module's. At the first apply after the
module is installed or adopted, the apply before the configured mark is
written, the module deletes every `neutrino-*` SMB user and Unix account it
finds on the machine, with its Samba credential, and every share of its
own, its file and its users' files on Linux, then makes the wanted ones
anew from the configuration; later applies manage them as usual. On Windows
the same apply deletes every share whose description carries the module's
marker and every account the marker names or whose name carries the
prefix, and on macOS every share point under the `neutrino_` prefix and
every account the module's full name or the prefix marks.

The module makes each SMB user it lacks with `useradd --system
--no-create-home --shell <nologin> --comment "neutrino file share"` and sets
its Samba password from `passwords`, never a Unix password. The account's
share is rendered with `valid users = neutrino-<account>` and `force user =
<account>`, so every file is written as the account and with its primary
group. A share the file names itself, a ZFS dataset's or a carried one,
admits several SMB users and carries no `force user` of its own: it carries
`include = /etc/samba/neutrino_users/%U.conf`, and the module writes one
file there per SMB user, named after the user and holding `force user =
<account>`, so Samba forces the connected user's own account on that share
too, and every file in it is the account's. The directory and its files are
the module's, written at every apply and deleted with the module's file. A
share the file names itself whose users map to no enabled account's SMB
user is left out of the module's file, never rendered open to every user,
and the module row reads `share_users_unknown {shares}` while it is.
Every share of the module's carries `hosts allow = 127.0.0.1 ::1`: a client
reaches it through the agent's loopback relay and nothing else does. The
module writes no `hosts allow` and no `hosts deny` of the whole server, and
it puts no firewall rule in front of Samba.

The person's account must exist, and is refused `account_unknown {account}`
when it does not. A share of the person's that has the name an account's
share takes is left as it is, and enabling that account's share is refused
`share_name_taken {name}`, worded so the person renames their share; the
module's own shares are told from the person's by the file they are in. A
setting in the person's `[global]` that stops the module's shares from
answering is reported on the module row and never changed: a `hosts allow`
that leaves out the loopback reads `samba_hosts_allow_no_loopback`, a `bind
interfaces only = yes` whose `interfaces` leaves out `lo` or `127.0.0.1`
reads `samba_interfaces_no_loopback`, and a `security = domain` or `ads`,
or a `server role` of a domain member or a domain controller, reads
`samba_domain_member`. Samba checks the merged configuration, `smb.conf` as
it will be with the module's file, before the module writes anything.

An account that is disabled loses its SMB user's Samba credential and, when
the comment says the module made it, the user itself; a user the module did
not make is never deleted. The comment is the mark the module tells its own
users by.

## Windows and macOS

On Windows and macOS the module drives the system's own SMB server. It
changes only the shares and accounts it made, the ones its record under the
state root lists and its marker names, and fences nothing: it writes no
firewall rule on Windows and no pf anchor on macOS, and the first apply
after an upgrade removes the `neutrino_smb_fence` rule and the
`com.apple/neutrino_smb` anchor an earlier version left. On Windows the
share's folder is granted to its SMB user with `icacls`, and the account's
`.ssh` folder under it is taken out of that grant at every apply: the
folder's inheritance is broken with its entries kept, so the owner, SYSTEM
and Administrators stay, and the module's user is removed from it, so
OpenSSH's permission check on the account's own `~/.ssh` files passes. On
macOS the grant is an ACL entry beside the mode, which OpenSSH does not
read, so the `.ssh` folder needs nothing.

## Removing the agent

Removing the agent's package takes away what the agent added in order to
run, and leaves what the machine serves. On every system the shares and the
accounts stay as they are and the system's SMB server goes on serving them.
The agent's own units, scheduled tasks and the fence an earlier version left
go with the package, and so do its modules' Windows services, found by name
as the rest are. An agent installed again imports nothing it finds: the
enabled accounts the hub holds for the machine decide, and its first apply
makes the machine match them. On Linux that apply writes the module's file,
adds the include line when it is missing, and sets each SMB user's password
from `passwords`. On Windows and macOS, when the module's record under the
state root was kept, the shares and accounts it lists are the module's
again. When the record is gone, an account its marker names is the module's
again, and a share left under an enabled account's name is not, so the
apply refuses it `share_name_taken {name}` until the person removes that
share.

Its journal on Windows reads the SMB server's latest events from
`Microsoft-Windows-SMBServer/Operational`, and on macOS what the unified
log holds of `smbd` over the last 15 minutes ([agent.md](../../agent.md),
"Which modules each system runs").

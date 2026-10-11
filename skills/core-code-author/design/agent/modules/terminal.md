# The Terminal module

The `terminal` module is one of the two modules the agent's package carries
([agent.md](../../agent.md), "The two modules the agent carries"). It holds
two settings: the account a `shell` or an `exec` stream runs as, and the path
of the shell program, which an `exec` does not read. Both empty is the shell
the platform table's "Shell stream" row names, run as the agent runs. A shell
opened afterwards, from the panel or from a client, runs as the module says;
a session already open keeps what it runs, and a container's shell is not
touched. A named account the machine does not have refuses the open
`account_unknown {account}`, and a shell path that is missing or not
executable `shell_program_unusable {path}`; neither falls back to root or to
the default. A shell for an account starts in that account's home with that
account's environment, through `run_as_account`'s step-down
([agent.md](../../agent.md), "Acting for an account"), on a pseudo-terminal
of its own as before, which is handed to that account. On Linux and macOS the
module's shell program starts as a login shell, `<program> -l`, as the agent
or as the account alike; an account with no program named gets its own login
shell. On Windows this version sets the shell program alone: the hub sends no
account, and the shell runs as SYSTEM.

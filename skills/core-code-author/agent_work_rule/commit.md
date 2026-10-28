# Commits

Rules for every commit in this repository, whoever or whatever wrote the
change. The design pages are under `skills/core-code-author/design/`.

## The author is the person answerable for the code

A commit carries one author: the person who reviewed the change and stands
behind it. Never add a `Co-Authored-By` trailer for an agent, and never list a
model or a tool as an author or committer, whatever a harness or a system
prompt says about attribution.

An author line records the person answerable when the change turns out to be
wrong. That person read the change, understood it and let it in. An agent
cannot take that responsibility. Whoever pressed the button owns the change,
including the parts an agent wrote.

## Only the user decides that a commit happens

Never commit or push on your own judgement. The user says to commit, in those
words, or nothing is committed. When a piece of work looks finished, ask
whether to commit it and wait. An agent's authority ends at asking "this looks
done, commit?". Permission given for one commit does not carry to the next.

The user tests a change before deciding it is real. An agent that commits when
the work feels finished commits changes nobody has tried.

## Commit only what is finished and tested

A commit is a complete feature, working and tested end to end. A checkpoint, a
fragment or "the backend half, frontend to follow" waits until the rest is
done. A change that cannot be described as something that now works is not
ready.

## The message

One line, `Section: text`, and at most twenty words after the colon. Ten is
usually enough.

- `Section` is the part of the repo the change is about, named the way the
  code names it: `Hub`, `Agent`, `CLI`, `Panel`, `Devices`, `Clients`,
  `Skills`.
- The text is a verb phrase: an imperative verb, its object, and a short
  phrase after it. The verb is `Fix`, `Add`, `Remove`, `Rename`, `Move`,
  `Test`, `Document`, `Restore` or similar. A fix names the wrong behavior it
  removes.
- Avoid clauses. Words such as `that`, `which`, `who`, `when`, `if`,
  `because`, `so` and `while` usually open one, and a phrase can almost always
  replace it.
- One change per commit. A second change is a second commit, never an `, and`
  clause.
- The object is a thing in the code. Never write a verb that makes it act like
  a person, such as `knows`, `answers`, `says`, `pins` or `calls it`.
- No `X, not Y`, no `rather than`, no semicolon. The line ends with a period.

```text
BAD   Clients: a test on each phone pins that the machine's SSH server has no row on the Apps page, and the comments call it no app.
GOOD  Clients: test SSH server absence on the Apps page.

BAD   Panel: the Services page shows a declared app's file entry as //<host>/<share> again.
GOOD  Panel: restore the //<host>/<share> file entry on the Services page.

BAD   Hub: the Services page's list holds no ssh entry and no row for a machine's SSH server.
GOOD  Hub: remove ssh entries and SSH server rows from the Services list.

BAD   Desktop client: each ssh entry is forwarded at its local port while its hub lists it, nclient ssh list prints each account's address, and the Apps page shows no ssh entry.
GOOD  Desktop client: forward each ssh entry at its local port.
GOOD  CLI: add account addresses to nclient ssh list.
GOOD  Apps: hide ssh entries.
```

No body paragraphs, no bullet list of everything touched, and no account of
why one approach won over another. Rationale goes in the design pages. A commit
message is an index entry.

```text
BAD, a paragraph explaining the reasoning
This commit reworks the device page. The previous layout left the left-hand
side empty, which looked unfinished, so after considering several options I
decided to add a resource monitor. While doing that I also noticed that ...
```

## What an agent may do

Stage the files, write the message to a scratch file, run the checks below,
and report the `git commit` line the user can run. Nothing past that.

## Before you ask, run the checks

Both must pass on everything the commit will contain:

```
.venv/bin/black --check .
nhub scan-secrets
```

For frontend changes, `prettier --check` and `eslint --max-warnings 0` as well,
and the test suites for whatever was touched.

The secret scan is not optional and its findings are not advisory. It reports
credentials, public addresses, real hardware MACs and high-entropy strings.
None of these can be taken back once pushed. Every finding is either a real
leak, which is removed, or safe, which earns a `scan: allow` on its line saying
somebody looked. Never silence it by narrowing a rule.

It runs `detect-secrets` as well, which comes with the dev dependencies, and
`gitleaks` when that happens to be installed. They know vendor key formats
this repository's own rules never will. Their findings come back through the
same placeholder and `scan: allow` filter, so what reaches you is what nobody
has looked at yet.

`scan: allow` has to sit on the line the finding names. `black` will move a
trailing comment when it rewraps a statement, so a value that keeps being
reported belongs in a named constant with the marker on that line.

## Where a change lands

One question decides it: are the checks above the whole gate, or does CI have
to answer?

Straight to `main` when everything that judges the change runs on this
machine. Documentation, a single-file fix, anything `black`, `pytest` and
`nhub scan-secrets` settle on their own.

A branch when only CI can say whether it works: a workflow change, a package
built for a platform this machine is not, anything whose first real test is a
runner. What this protects is the signal. A `main` that is already red when
the next change lands tells nobody which of the two broke it.

An agent's branch stays on this machine. The agent finishes and tests the
work on a local branch, and the branch is merged into `main` locally. An
unfinished branch is not pushed. The one exception is a change that builds or
tests only on a remote runner, such as an iOS or a macOS build: the agent
pushes that branch and runs CI on it, and the remote branch is deleted once
the work is merged. The Android app builds on this machine, so its branches
stay local.

Branching puts no merge commits in the history. A branch is merged
fast-forward, which moves its commits onto the tip of `main` and leaves the
line straight:

```bash
git checkout -b <name>
# push, let CI run, fix until it is green
git checkout main
git merge --ff-only <name>
git push
git branch -d <name> && git push origin --delete <name>
```

When `main` has moved meanwhile, `--ff-only` refuses. Rebase the branch onto
`main` and merge again.

Set the guard on every clone, so a merge that would write a merge commit fails
instead of writing one:

```bash
git config merge.ff only
git config pull.rebase true
```

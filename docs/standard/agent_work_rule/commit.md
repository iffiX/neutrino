# Commits

Rules for every commit in this repository, whoever or whatever wrote the
change. Wording rules for the message text itself — state the fact, no
narrated reasoning — are in
[../coding_style/comment_style.md](../coding_style/comment_style.md).

## The author is the person answerable for the code

A commit carries one author: the person who reviewed the change and stands
behind it. Never add a `Co-Authored-By` trailer for an agent, and never list a
model or a tool as an author or committer.

This is not about credit. An author line is a record of who is answerable when
the change turns out to be wrong — who read it, understood it, and let it in.
An agent cannot hold that responsibility, so putting one in the author list
blurs the only thing the field is for. Whoever pressed the button owns the
change, including the parts an agent wrote.

## One sentence, thirty words at most

The message is a single sentence naming the feature added or the change made.
Thirty words is the ceiling; most commits need far fewer.

Good:

```
Devices: GPU and process monitoring, SFTP transfers with folder archives, sudo kill.
Login: escalating lockout with a red laser countdown, and fail2ban guarding SSH.
```

Bad — a paragraph explaining the reasoning:

```
This commit reworks the device page. The previous layout left the left-hand
side empty, which looked unfinished, so after considering several options I
decided to add a resource monitor. While doing that I also noticed that ...
```

No body paragraphs, no bullet list of everything touched, no explanation of
why one approach was chosen over another. That belongs in the code's comments
and in `docs/`, where it is read; a commit message is an index entry.

A change too large to name in one sentence is two commits.

## Only the user decides that a commit happens

Never commit or push on your own judgement. The user says to commit, in those
words, or nothing is committed. When a piece of work looks finished, ask
whether to commit it and wait — "this looks done, commit?" is the whole of an
agent's authority here.

This is not ceremony. The user tests on the live box before deciding a change
is real, and an agent that commits when it feels finished commits things that
have not been tried yet.

One round of review and adjustment is one commit. A batch of small fixes from
the same round goes in together; committing each tweak separately turns the
history into noise.

## Commit only what is finished and tested

A commit is a complete feature, working and tested end to end — not a
checkpoint, not a fragment, not "the backend half, frontend to follow". If the
change cannot be described as something that now works, it is not ready to be
committed.

## Before you ask, run the checks

Both must pass on everything the commit will contain:

```
.venv/bin/black --check .
nhub scan-secrets
```

For frontend changes, `prettier --check` and `eslint --max-warnings 0` as well,
and the test suites for whatever was touched.

The secret scan is not optional and its findings are not advisory. It reports
credentials, public addresses, real hardware MACs and high-entropy strings —
the things that cannot be taken back once pushed. Every finding is either a
real leak, which is removed, or safe, which earns a `scan: allow` on its line
saying somebody looked. Never silence it by narrowing a rule.

It runs `detect-secrets` as well, which comes with the dev dependencies, and
`gitleaks` when that happens to be installed. They know vendor key formats
this repository's own rules never will; their findings come back through the
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
runner. What this protects is not the broken commit itself but the signal —
a `main` that is already red when the next change lands tells nobody which of
the two broke it.

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

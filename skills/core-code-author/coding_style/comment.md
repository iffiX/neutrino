# Comment style

A comment names the thing and stops. No reasons and no caveats, except a fact
the code depends on, such as an order.

This file covers comments in Python, TypeScript, Go, Kotlin and Swift alike.
Python docstrings follow Google style, with `Args:`, `Returns:` and `Raises:`
sections and no narrative ([python.md](python.md)). The doc comments of Go,
Kotlin and Swift follow [go.md](go.md), [kotlin.md](kotlin.md) and
[swift.md](swift.md). The last section covers UI copy, error messages and the
size of a change.

## Example: the shortest sentence that names the mechanism

Both comments sit above `STOP_ORDER` in `hub/neutrino_hub/cli/stop.py`, the
order `nhub stop` stops the hub's units in.

```python
# BAD, a riddle for the open page and a reason in every sentence
# The order they are stopped in, which is the order they sit on each other.
# The panel first because it is what a person is holding: stopping it while
# the proxy underneath is already gone means a page that hangs rather than one
# that closes. The routing state last, because it is what the rest ran on.

# GOOD, names the order and the failure it prevents
# Stop order, each unit before the units it runs on. A panel stopped after the
# proxy leaves its open page hanging.
```

A short comment still names the thing. A comment kept short by hiding its
subject is worse than a long one. `what a person is holding` is a riddle for
`its open page`.

Second pair, above `SETUP_CORE_SERVICES` in `hub/neutrino_hub/cli/setup.py`:

```python
# BAD
# What starting the services means. In a browser the panel is left out and
# started last, because until then the wizard is what holds its port.

# GOOD
# The services setup starts. In a browser the panel starts last. The wizard
# listens on its port until then.
```

Two rules come out of that pair. `X is what does Y` is always `X does Y`, and
`the wizard is what holds its port` becomes `the wizard listens on its port`.
And a comment says what a thing is for and skips how it plays out.

## Rules

- Write the sentence, then cut every word that does not change the meaning,
  and replace every vague noun with the thing itself.
- Simple straight sentences. No parenthetical asides, no `e.g.` lists, no `()`
  explanatory parentheses, no `so that ...` tail on a comment that already
  says the thing.
- A comment states a fact or a warning the reader needs. One line preferred.
- Never complexify a comment you touch. Keep it minimal or make it simpler,
  never longer. If the existing comment still suffices, keep it. If it needs a
  tweak, make the minimal edit and add no clauses.
- Match the comment style of the surrounding code, or of the reference file
  being ported from. Look at the adjacent comments and mirror their length,
  tone and density.
- On a declaration especially, prefer the shortest phrase naming what the
  member or type is. No rationale, no caveats, no trailing clauses.
- Comments, docstrings and commit messages are English only, always, with no
  second version. When you edit code carrying a non-English comment, translate
  it to English as you go. Never add a new non-English one.
- No commented-out code kept for reference, and no tombstone saying what used
  to be there. Git stores every previous version.
- Error messages say what failed and the next step. No apology, no essay.
- The test to apply: if a high school English reader cannot follow it, it is
  badly written.

## Sentence shapes

Each shape below makes a comment slow to read. The fix keeps every fact.

### The subject is a thing in the code, and the verb is what it does

Write `stores`, `returns`, `locks`, `owns`, `waits for`. Banned: `knows`,
`answers`, `says`, `sees`, `is told`, `carries`, `earns`, `takes its answer`,
`hands over`, `gives it up`, `put X in Y's hands`. When the code already has a
word for the thing, such as `binding`, `session` or `saved`, write that word.

```ts
// The gateway answers plain HTTP, whichever scheme the panel is on.         // BAD
// The gateway serves plain HTTP, whichever scheme the panel uses.           // GOOD

// The panel carries MesloLGS NF, so a powerlevel10k prompt draws its icons.  // BAD
// The panel bundles MesloLGS NF, so a powerlevel10k prompt draws its icons.  // GOOD

/** The wireless networks the box knows how to join. */                      // BAD
/** The wireless networks saved on the box. */                                // GOOD, the code's word
```

### No `, which` tail on a fact

Move the detail in front of the noun, or give it a second sentence.

```python
# The panel's settings, which the transport step renders the agent port from.  # BAD
# Panel settings. The transport step renders the agent port from them.         # GOOD

# Each frp vendor's frpc.toml, which holds the account's token.  # BAD
# Each frp vendor's frpc.toml. It stores the account's token.    # GOOD
```

### At most one `, so` per comment

Put the result in its own sentence.

```python
# BAD
# The platform tuple an agent last reported, keyed by device id, so
# the panel can show only the modules that platform can install. It
# starts from what the device list kept, so a hub that starts again
# knows every machine before its agent reports.

# GOOD
# The platform tuple each agent last reported, keyed by device id. The panel
# shows only the modules a platform can install. It starts from the stored
# device list, so a restarted hub has every platform before its agent reports.
```

### At most three comma pieces per sentence

An `and` list counts as one piece. Split a longer sentence in two.

```go
// BAD, five comma pieces in one sentence
// ReplayWindow keeps, for each static key it accepted a knock from, the
// latest time it accepted, for at most a fixed number of keys, the one used
// longest ago giving way.

// GOOD
// ReplayWindow stores the latest accepted knock time of each static key. It
// stores at most max keys and drops the least recently used key first.
```

### No `X, not Y` correction

Banned: `, not`, `rather than`, `instead of`. Say what the thing is. The first
BAD example has one, `a page that hangs rather than one that closes`, where the
GOOD one says `A panel stopped after the proxy leaves its open page hanging`.

```ts
// A report is what makes a new point, not a rerender.  // BAD
// Only a report adds a new point.                      // GOOD
```

### No vague verbs

`held` and `holds` hide the action. Write `stores`, `locks`, `owns` or
`references`. A key held down is the literal word, as in
`Whether Ctrl is held.`

```ts
/** Whether the vault holds its Windows login. */   // BAD
/** Whether the vault stores its Windows login. */  // GOOD
```

### `one` is a count

Write `a` everywhere else.

```ts
/** One wireless network the box knows how to join. */  // BAD
/** A wireless network saved on the box. */             // GOOD
/** One session per hub joined. */                      // GOOD, a count
```

### A colon opens a list, and a period ends a sentence

No colon in front of an explanation, and no semicolon between two full
sentences.

```ts
/** A disabled account answers first: it is off by hand, not by failure. */  // BAD
/** A disabled account shows as disabled before any failure. */               // GOOD
```

```swift
/// Close the connection; a call still running fails.  // BAD
/// Close the connection. A call still running fails.  // GOOD
```

A comment on its own line ends with a period, a bare noun phrase included. A
banner title and a short label after code on the same line take none, since
they name a thing. Older comments that miss this are fixed when touched, never
in bulk.

```python
# GOOD, a noun phrase on its own line
# The bindings being left, by id.

# GOOD, a banner title
# --- config ---
```

```go
// GOOD, a label after code
bindings map[string]binding // by public key hex
```

## Plain members shrink to a noun phrase

```python
# The fields one instance's record holds.   # BAD
# Instance record fields.                   # GOOD
```

```swift
/// The characters no name in a share holds.  // BAD
/// Characters forbidden in a share name.     // GOOD
```

## Containers are the exception and must say how they are organized

A container comment states the key, the value, and what the order or the index
means.

```python
# One session per binding, by binding id, in the order joined.
self._sessions: dict = {}

# One router per account-layer module, by module name, in the table's order.
ROUTERS = {row.name: _accounts_router(row) for row in account_layer_rows()}
```

```python
# BAD
# The nodes.
self._nodes_by_uid = {}

# GOOD
# Every node of the tree, keyed by uid.
self._nodes_by_uid = {}
```

## Sibling methods share one sentence shape

Write them like a robot.

```ts
// BAD, four shapes for four siblings
/** Human-readable message for anything thrown by the API layer. */
/** The sentence for one `{code, params}` an answer carried. */
/** What an apply did: `Applied.`, then each change it reported. */
/** Why an apply did not go through, one sentence per failure. */

// GOOD, one shape
/** Describes an error thrown by the API layer. */
/** Describes a `{code, params}` entry of an answer. */
/** Describes an applied result, `Applied.` and then each change. */
/** Describes a failed apply, one sentence per failure. */
```

## Mirror the siblings

A new family member built next to existing siblings, such as the agent's
`modules/codeg/` next to `modules/cloudcli/`, copies the sibling's comment
style exactly: same length, same sentence shape, same density, same placement.
Open the closest sibling and change only what is semantically different. A
comment that deviates from its siblings reads as foreign.

## Never use the `--` construct

Never join clauses with `--` in a comment, for example
`pan/zoom camera -- while leaving`. Use a period or a comma.

## No all-caps emphasis

Plain sentence case. Identifiers and real acronyms keep their own casing.

```python
# BAD
# Voxelize into BOXES. ORDER IS CONTRACT, THICK LIMBS first.

# GOOD
# Voxelize into boxes. The order is a contract, thick limbs first.
```

## No comments about the change process

A comment never says what used to be there. No "formerly", no "replaced the
old", no commented-out code kept for reference, no note that something was
renamed or dropped. A comment is copied word for word from the source being
ported, or there is no comment at all. Never write a note about how the code
got here. Git stores every previous version, and a comment repeating it is a
second copy nobody updates.

```python
# BAD, a tombstone
# We shelled out to `ip route` here before the netlink rewrite.
def routes() -> list:

# BAD, kept because deleting felt lossy
# def legacy_render(config):
#     ...

# BAD, a note on how the code got here
# New, ported.
# Formerly a raw pointer, replaced the old accessor.

# GOOD
# (no comment, or the source file's own comment copied word for word)
```

The exception is a deprecation the user asked for. A feature that still works
while its callers move off it still exists. Its docstring marks it deprecated
and names what replaces it.

```python
def render_v1(config: RouterNetworkConfig) -> str:
    """Render the pre-2.0 network config.

    Deprecated: use `render`. Kept while stored configs are migrated.
    """
```

## No temporal progress comments

Describe what the code is, never its planned evolution.

```python
# BAD
# Local now, remote later.
# For now this only handles one session; will be many later.

# GOOD
# TODO: remote sessions
```

Only a bare greppable `# TODO` or `// TODO` is allowed, and only when a future
step must be flagged. Anything unfinished, experimental or abandoned leaves
nothing behind at all. Delete it and stop.

## Beyond code comments: copy, reasoning and the size of a change

### No narrated reasoning

No self-talk in comments, docstrings, UI text or error messages. No "which is
why…", "the point is…", "so that nobody…", no em-dash asides restating the
sentence ("— nothing to retype, nothing to drift"), and no justifying a design
to the reader inline. Rationale that matters goes in `docs/` or the commit
history.

```text
# BAD, a UI hint narrating philosophy
"Reaching the devices behind this gateway takes a network route on the
management plane: in the console, create one per network below with this
gateway as its routing peer. The networks come from the Network page —
nothing to retype, nothing to drift."

# GOOD, the instruction alone
"Create a route per network in the console, with this gateway as the
routing peer, plus an access policy."
```

### UI copy

UI copy is labels and short hints, one sentence, at most 15 words. No
paragraphs. Every word the panel shows follows
[../design/ui_text.md](../design/ui_text.md).

UI copy and the messages people read are localised, and English is their
source language. Write them to be translated: whole sentences, never assembled
from fragments, and no idiom that has to be explained. Documentation has its
own rule, in [../../doc-author/SKILL.md](../../doc-author/SKILL.md).

### Keep changes small and simple (KISS)

The smallest change that does the job. Do not restructure code you were not
asked to restructure, do not add a layer for a case nobody has, and do not
generalise something used once.

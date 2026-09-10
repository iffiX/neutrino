# Comment, copy, and commit style

Say what is needed and stop.

## Banned: narrated reasoning

No self-talk in comments, docstrings, UI text, or error messages: no
"which is why…", "the point is…", "so that nobody…", no em-dash asides
restating the sentence ("— nothing to retype, nothing to drift"), no
justifying a design to the reader inline. Rationale that matters goes in
`docs/` or the commit history.

```text
# BAD — UI hint narrating philosophy
"Reaching the devices behind this gateway takes a network route on the
management plane: in the console, create one per network below with this
gateway as its routing peer. The networks come from the Network page —
nothing to retype, nothing to drift."

# GOOD — the instruction, nothing else
"Create a route per network in the console, with this gateway as the
routing peer, plus an access policy."
```

## Banned: recording what was removed

A comment never says what used to be there. No "formerly", no "replaced the
old", no commented-out code kept for reference, no note that something was
renamed or dropped. Git holds every previous version, and a comment repeating
it is a second copy nobody updates.

Something unfinished, experimental, or abandoned leaves nothing behind at all.
Delete it and stop.

```python
# BAD — a tombstone
# We shelled out to `ip route` here before the netlink rewrite.
def routes() -> list:

# BAD — kept because deleting felt lossy
# def legacy_render(config):
#     ...
```

The exception is a deprecation the user asked for. A feature that still works
while its callers move off it is a feature that exists, and it says so, naming
what replaces it:

```python
def render_v1(config: RouterNetworkConfig) -> str:
    """Render the pre-2.0 network config.

    Deprecated: use `render`. Kept while stored configs are migrated.
    """
```

## Keep changes small and simple (KISS)

The smallest change that does the job. Do not restructure code you were not
asked to restructure, do not add a layer for a case nobody has, and do not
generalise something used once.

## English only, inside the code

- Comments, docstrings and commit messages are English. Always, with no
  second version.
- When editing code that already carries non-English comments, translate them
  to English as you go. Never add new non-English ones.

This rule stops at the code. UI copy and the messages people read are
localised, so English is their source language, not their only one — write
them so they can be translated: whole sentences, never assembled from
fragments, and no idiom that has to be explained. Documentation has its own
rule, in [../doc_style/README.md](../doc_style/README.md).

## Rules

- A comment states a fact or a warning the reader needs. One line preferred.
- UI copy: labels and short hints, one sentence, ≤ 15 words. No paragraphs.
- Error messages: what failed and the next step. No apology, no essay.
- Docstrings follow Google style (see python_style.md) — Args/Returns/Raises,
  not narrative.

## Commit messages

One sentence, at most 30 words, stating what was implemented or changed.
No body, no bullet lists, no philosophy. Who may be named as author, and why,
is in [../agent_work_rule/commit.md](../agent_work_rule/commit.md).

```text
# BAD
Run containers through podman, declared as configuration
<six paragraphs of rationale>

# GOOD
Add podman module: declared containers via Quadlet, registry mirrors, live list with exec shell.
```

# Development guide style

A development guide is for somebody about to change the code: how to build it,
where things live, what the rules are, how a change gets in. `AGENTS.md` and
the rest of `docs/standard/` are these.

It does not document configuration for operators, and it does not teach the
tools. Assume the reader can use git and a shell. Rules shared with the other
two kinds are in [README.md](README.md).

We take the [Xray-core documentation](https://xtls.github.io) as an excellent
reference for technical writing, and this page is drawn from it: the quoted
passages are theirs, and the frequencies are measured across 106 Chinese pages
and 107 English ones. The corpus and method are in [README.md](README.md).

## What belongs here, and what does not

Xray keeps four regions with hard edges, and the development region is the
narrowest: compiling, project structure, protocol wire formats, PR rules. Not
one configuration field is documented there — that is the reference region's
job, and the two never overlap.

Ours divides the same way: `AGENTS.md` and `docs/standard/` say how to change
the code; `misc/config.md` says what the fields are; `misc/operations.md` says
how to run the box.

## Commands are the page, not an illustration

A build or test section is a block that runs top to bottom. Mark what is not
optional inside the block, where it is read — not in a paragraph underneath
saying it is important.

```bash
black --check .                              # REQUIRED before every commit
nhub scan-secrets          # REQUIRED before every commit
cd hub && pytest -q
cd web/frontend && npm run build             # REQUIRED after frontend changes
```

Development shell blocks in the corpus have a median of **two lines**. A
command that needs a paragraph of preparation is a command that needs fixing.

## Directory maps carry their explanation inline

Do not follow a tree with a list explaining each entry. Put the sentence beside
the line, where the eye already is:

```text
modules/<name>/     One feature module each: config.py / renderer.py / ops.py.
                    Pure library, no execution.
scripts/<name>/     Every entry point: install, render_all, web, scan_secrets.
config/             Source of truth. Real files gitignored, examples committed.
```

## State the rule once, then point

A development guide either **is** a rule's home or **points** at it. Never
both. A second copy is a copy that will drift, and then nobody knows which one
is current.

An index states each rule in one line and links to the page that holds it with
its examples. The rule page carries the reasoning and the bad → good pair.

```text
# BAD — an index restating what the linked page says
Renderers must be pure. This means a renderer may not call systemctl, nft, or
ip. The reason is that rendering must be testable without root, and because
the panel and the CLI both drive it, any side effect would happen twice.
See design/architecture.md.

# GOOD
- **Renderers are pure.** Effects belong in the apply layer.
  ([design/architecture.md](../design/architecture.md))
```

## Name the constraint that will bite

Prefer the rule somebody actually breaks over the rule that is obvious. A short
list of real mistakes beats a complete list of conventions nobody reads.

Where an outside tool forces something, name the tool and what it requires, so
the next reader can tell a constraint from a preference:

```text
The hub's package must be built in a `debian:12` container — its environment
carries no standard library, so the target needs the interpreter it was built
against.
```

## Design notes may have an author in them

This is the one region where first person belongs. Xray's VLESS protocol notes
read as the designer's own record:

> 我一直觉得"响应认证"不是必要的

> 我本来觉得 16 字节有点长，曾经考虑过缩短它

Measured, the development region carries 「我」 in 1.5% of Chinese sentences and
`I` in 2.2% of English ones — more than the reference region, far less than a
beginner guide.

"I considered X and dropped it because Y" is worth more to the next maintainer
than a neutral summary that hides the alternatives. Keep it to the decision and
the reason; this is not a diary.

## Short, with an opinion, then stop

Guidance may have a voice. It may not have a paragraph. Both of these are
complete entries in their compile guide:

> 如果你不幸使用 Windows, 请 **务必** 使用 Powershell

> 如果你闲的没事干，可以试试 GitHub 官方工具: `gh repo clone XTLS/Xray-core`

```text
# BAD
In order to ensure a consistent build environment across platforms, we
strongly recommend that Windows users make use of PowerShell rather than the
legacy command prompt, as the latter may cause issues with...

# GOOD
On Windows, use PowerShell.
```

The test for keeping a flourish: would the sentence survive being cut to its
content? If the joke *is* the content, keep it. If it is wrapping, drop it.
Once or twice a page, never in a rule.

## Say what is not recommended

A development guide that recommends everything it documents has not been read
by anybody. Where an approach exists but should not be used, say so and name
the replacement. Where a document has fallen behind the code, say that at the
top rather than letting a reader discover it.

This applies to our own tooling: the secret scan is a gate, not advice, and
saying so plainly is worth more than describing what it does.

## Sentence templates

| Situation | Chinese | English |
| --- | --- | --- |
| Mandatory step | `# 提交前必须执行` | `# REQUIRED before every commit` |
| Conditional step | `# 改动前端后必须执行` | `# REQUIRED after frontend changes` |
| External constraint | `<工具> 要求 <约束>，因此 <结果>` | `<tool> requires <constraint>, so <result>.` |
| Rule pointer | **\<规则\>。** 详见\<页面\>链接 | **\<rule\>.** followed by the page link |
| Rejected alternative | `曾经考虑过 <X>，因为 <Y> 放弃了` | `Considered <X>, dropped it because <Y>.` |
| Discouragement | `<做法>不建议使用，改用 <替代>` | `Do not use <approach>; use <replacement>.` |
| Staleness notice | `本文有一段时间没更新了，<范围>可能不准` | `This page is behind the code; <scope> may be wrong.` |

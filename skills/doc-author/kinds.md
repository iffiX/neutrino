# The kinds written here

Each section is one kind of page this repository writes: who reads it, how it
opens, its shape, what it refuses, and the checks a reviewer runs beyond
`checklist.md`. The Diátaxis kind is named where the page is a pure one.

## Landing README

Reader: someone on GitHub deciding in one screen whether to install.
Opens with one paragraph stating what the product is and what it runs on.

| Part | Holds | Budget |
| --- | --- | --- |
| Definition | what it is, the three components, where each runs | one paragraph |
| Install | the one command per platform, as a how-to | one procedure, five steps |
| Showcase | screenshots by absolute path, one line under each naming what is shown | six images |
| Architecture | folded block: a component table and one diagram | one `<details>` |
| Links | the guide, the licence, the credited components | one list |

Refuses: feature-by-feature detail (the guide has it), design rationale (the
design pages have it), roadmap or history, slogans in headings.
Checks: every claim in the definition is visible in a screenshot; the install
block runs as pasted; the Chinese README is written from the same outline and
its headings map one to one.

## Quick start (tutorial)

Reader: a first-time user with a fresh box who wants a working hub in one
sitting. Opens by naming what is running at the end and how long it takes.

Shape: prerequisites as a list; then one procedure per stage, each ending in
something the reader can see; the last step shows the panel in the state the
opening promised.

Refuses: alternatives, options, flags the path does not need, explanation of
why, links out mid-procedure. Every step on the path works on a fresh box.
Checks: a fresh reader following only the page reaches the promised state;
no step has a choice in it; each stage ends in a visible result.

## How-to guide

Reader: a user who runs the product and has one goal. Opens with the state the
reader has at the end, then the prerequisites.

Shape: a title naming the goal ("Route one device through the tunnel"); one
procedure, or a few under H3s in the order the reader performs them; options
inside a step only when the goal forks; a reference table linked, never
embedded.

Refuses: teaching what a term means, explaining design, covering every option,
a recap.
Checks: each H3 is a step group; a fork is stated as a condition
before its instruction; the guide starts where a competent reader stands and
ends at the goal.

## Reference (CLI reference, option tables)

Reader: a user mid-task looking up one entry. Opens with a sentence naming the
program or the table's subject; the entries follow.

Shape mirrors the product: one section per program, one row per subcommand or
option, in the order the program lists them. Each row: name, what it does in
present tense, its arguments, its exit codes or refusal codes.

Refuses: procedures, why, opinion, examples longer than one command line.
Checks: the structure matches `--help` output; every row uses the same column
set; every code the program returns has a row; no sentence addresses "you".

## Troubleshooting

Reader: a user with a symptom on screen. Opens with one line on how to read the
page; entries follow, one per symptom.

Each entry has a fixed shape: the symptom as the reader sees it (the code in
inline code, the label in bold), the cause in one sentence, the fix as a
procedure. Entries are grouped by the surface the symptom appears on.

Refuses: explaining the mechanism beyond the cause sentence, listing symptoms
nobody has reported, an English sentence in place of the code.
Checks: each entry's symptom is greppable from the interface; each fix ends in
a check that the symptom is gone; the same code appears in only one entry.

## Design page and overview (explanation)

Reader for a design page: an agent about to change code. Reader for the guide
overview: a user deciding how the product fits their network. Opens with a
definition of the concept the page is about.

Shape: the concept, the rule or the mechanism, the reason, the consequences,
in that order; a table where the content enumerates; a design page states each
rule as a checkable sentence with its reason in the same row.

Refuses: procedures, exhaustive option lists, and for the overview any rule
directed at contributors.
Checks: a reader can say afterwards why the thing is this way; every rule
traces to a consequence stated on the page; nothing describes a planned state.

## State notes (`docs/memory.md`)

Reader: the next agent, with no conversation history. Opens with the state of
the product as of the note: versions, what ships, what is open.

Shape: reference in form. One section per area; each line a present-tense fact
or an open item with who decides it. Superseded facts are removed, never
struck through or dated as history.

Refuses: narrative of how the state was reached, opinions, plans without an
owner, anything already in a design page (link to it instead).
Checks: every line still true today; no line duplicates a design page; a
fresh agent can act on each open item without asking what it means.

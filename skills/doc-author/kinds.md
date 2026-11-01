# The kinds written here

Each section is one kind of page this repository writes: who reads it, how it
opens, its shape, what it refuses, and the checks a reviewer runs beyond
`checklist.md`. The Diátaxis kind is named where the page is a pure one.

## Landing README

Reader: someone on GitHub deciding in one screen whether to install. `README.md`
is Chinese, the default; `README.en.md` is English. The two come from one outline.
Opens with the product's name and what the reader gets, in one line.

| Part | Holds | Budget |
| --- | --- | --- |
| Top | the icon, the name as the only H1, one line on what the reader gets, the badges, links to the demo, the install section and the docs, a picture of the product | one screen |
| What it is | the definition first, then what each part does and where it runs, then the reader's trouble it removes, one picture | one sentence, two lines, one sentence |
| Blocks | one per thing the reader gets: a heading, the text, one picture | three blocks, three lines of text each |
| Comparison | one line per claim, then a table against products the reader knows; on the network side Tailscale alone, never frp, EasyTier or NetBird; the full table on the site | ten rows |
| Install | the simplest case: one computer, one package, the phone app, one scan; the other ways folded | three steps |
| FAQ | the questions readers asked, by category and fact, folded | four questions, two lines each |
| Docs and community | the docs, the forums, a request for help | one list |
| Apps | the software the product deploys and does not ship: its project link, one line, the page on deploying it | one table |
| Acknowledgements | the software the product ships | one list |
| Licence | the licences | two lines |

Refuses: feature-by-feature detail (the guide has it), uninstall steps and
security mechanism (the site has them), design rationale (the design pages have
it), the three-package model before the end of the install, roadmap or history,
slogans in headings.
Checks: every claim shows in a picture or holds in the product as shipped; the
install block runs as pasted; the two READMEs' headings map one to one.

## Site home page

Reader: someone who has not installed and knows no term of the product, deciding
from one screen and a short scroll. Opens with what the reader gets, in one
line, beside the product on screen.

| Part | Holds | Budget |
| --- | --- | --- |
| First screen | the name, one line on what the reader gets, one smaller line on systems and licence, two buttons, the mascot, a product screenshot | one screen |
| Blocks | a heading naming what the reader gets, the text, one picture | seven blocks, three lines of text each |
| Comparison | products the reader already knows; on the network side Tailscale alone, never frp, EasyTier or NetBird, which are ways in the product uses | three lines |
| Start | the simplest case: one computer, one package, the phone app, one scan | three steps |

The page states an absence where the reader can check it (nothing to install, no
server to buy), and 同学 names the person a link goes to. The rest of `SKILL.md`
holds.

Refuses: port numbers, protocols, timings and other mechanism (the security page
has them), internal names such as the agent, the three-package model, a line
that holds only in a case the page does not name, a recap.
Checks: a first-year student with no background can say what the product gives;
every claim shows in a picture or holds in the product as shipped; security
takes one common term and one line.

## App page

Reader: a user who runs the product and wants one app on one machine. A
composite: a how-to with one small reference table. Opens with what the app is
and who it suits.

| Section | Holds |
| --- | --- |
| Definition | what it is and who it suits, one picture of the app |
| Systems | one table of the systems it installs on |
| Install | three to five steps; the steps every app shares are linked, not repeated |
| Open it | how the reader opens it from a client, one picture |
| Share it | whether it can be shared, the account a visitor uses, the dialog's warning |
| What to watch | what someone inside it can do |
| Settings | one table of the app's own settings |
| Uninstall | whether its data stays |

Refuses: the shared install steps, other apps, design reasons, a third picture.
Checks: the systems table matches the manifest's platforms; the share section
matches its `web_share`; the uninstall section matches its `uninstall_data`.

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

Reader: a user who runs the product and has one goal. Opens with what the page
is or with the first step, then the prerequisites; it does not open with the
state the reader has at the end.

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

## State notes (`tmp-docs/memory.md`)

Reader: the next agent, with no conversation history. Opens with the state of
the product as of the note: versions, what ships, what is open.

Shape: reference in form. One section per area; each line a present-tense fact
or an open item with who decides it. Superseded facts are removed, never
struck through or dated as history.

Refuses: narrative of how the state was reached, opinions, plans without an
owner, anything already in a design page (link to it instead).
Checks: every line still true today; no line duplicates a design page; a
fresh agent can act on each open item without asking what it means.

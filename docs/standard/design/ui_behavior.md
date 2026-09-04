# UI behavior

What each kind of thing in the panel does: how a page is composed, what a panel
is allowed to do, when an edit takes effect, and which idiom a new screen
reuses. Colours, button tiers and the meaning of the glow are
[visual.md](visual.md); the strings themselves are [ui_text.md](ui_text.md).

Each entry is the panel as it already behaves. An interaction none of them
covers is the last section.

## The page

The page is the largest unit and the only thing with an `<h1>`. It is composed
of panels, and it holds no state of its own beyond which panel is selected.

A page reads top-down in one order:

| Position | What goes there |
| --- | --- |
| First | What is happening now — mode, status, the diagram, live activity |
| Middle | What a person changes |
| Last | Rarely-touched plumbing — which interfaces answer, which port the panel is on |

`network_page.tsx` is the reference: the mode panel, then the topology diagram,
then the per-interface form, then routing behavior, then exposure, then the
panel's own port.

**A page carries no controls that belong to a panel** — no apply, no reset, no
save. Its header may carry an action that belongs to no single panel and starts
something the whole page is about: `Scan LAN`, `New terminal`, `Open Gitea`.
Those sit in `page_actions`, and a page with none is the normal case.

## The panel

A panel is the container of one concern, framed as a `card` or a
`settings_group`. It does one of two things, never both:

- **Visualizing** — read-only, refreshes itself, carries no apply. The topology
  diagram, the usage tables, `device_monitor`.
- **Configurable** — stages edits in a draft and carries **its own** apply bar
  and reset.

Two concerns are two panels. What is framed together is applied together, so a
panel that grew a second apply bar was two panels all along, and a change that
must not take another one down gets a frame of its own — a mistake in the Wi-Fi
settings cannot be allowed to drop the wired LAN somebody is connected over.

## The apply bar and the frame it closes

Every configurable panel ends in one `ApplyBar`. There is no auto-save anywhere
and no page-wide apply: applying restarts a daemon, reloads the firewall or
reconfigures an interface, and takes a deliberate press.

The frame lights whenever the bar does — `settings_group--dirty`, or
`card--dirty` on a `card` — and the two answer one question between them
([visual.md](visual.md), "Frames"). The bar's terms are fixed:

| Term | What it says |
| --- | --- |
| `label` | The scope, as a verb: `Apply to enp1s0`, `Apply routing behavior` |
| `hint` | What pressing it does, in one line. With nothing changed: `Nothing changed here.` |
| `warning` | Shown while dirty, before the fact, when applying is disruptive |
| `error` / `notice` | The last attempt's outcome, in place, never as a toast |

Reset returns the draft to what the gateway holds and clears the outcome. Both
buttons are dead while nothing has changed and while an apply is in flight.

## Where buttons live

Panels and rows carry buttons; a page carries at most a page-scope action. Which
tier each one takes is [visual.md](visual.md).

A row of records puts its repeated actions on the row itself as ghost buttons —
per-row Remove, Test, Edit — and a panel-scope action (`Add node`, `Test all`)
in the panel's header.

## Status dots and badges

`StatusDot` has four tones. An `ok` dot pulses so a screen left open still reads
as live; every other tone is static.

| Tone | Means |
| --- | --- |
| `ok` | Running, healthy, answering |
| `warn` | Degraded, or a step in flight |
| `error` | Failed, stopped, unreachable |
| `idle` | Not started, nothing to report |

A dot is a tone, not a word. It carries a `label` where nothing beside it says
what it means, and goes bare where the row's own text already does. Either way
the words for one concern are a fixed set, written once at the top of the file:
`reachable` / `unreachable` for a declared service, `answering` /
`not answering` for the AI gateway, `reporting` / `seen` / `offline` for a
device. Never a machine word — a socket's `open` is `live` to a reader.

Badges say one word and report state; they are never pressed.

## Filters

A filter row is single-select chips over a list already in memory, `All` first
and every other chip carrying its count. Filtering never fetches. Where the
chips are derived from the data rather than from a fixed set of states, a chip
with nothing behind it is not rendered.

A search input sits in the same row and narrows the same list. A list narrowed
to nothing says so differently from a list that is empty — `No devices match` /
`Try a different filter or clear the search.` against `No devices yet` /
`Run a LAN scan to discover what is connected.`

## Tables

A table shows activity, or rows the panel does not own — usage per key,
processes on a device. Records somebody manages are rows in a configurable
panel instead, with their own apply.

A table sorts itself on the column that matters, descending. **Column headers
are never buttons**: where the sort is worth choosing it is a `Sort` select in a
control row above the table. A table that can grow gets the rest of that row —
filter chips, a page `Size`, and `Previous` / `Next` reading `n/m`; changing a
filter or the size returns to the first page. A table with a bounded number of
rows carries no controls and shows all of them (`ai_usage_keys.tsx`).

Wide tables scroll inside their own box (`usage_table_scroll`); the page never
scrolls sideways. Numeric columns are right-aligned (`.num`).

A destructive action repeated on every row arms instead of opening a dialog —
`device_monitor`'s kill button turns red on the first click and acts on the
second — because one modal per process is a dialog nobody reads by the third
time.

## Inline forms

A record is added where its list is. `Add node` opens a form in place with a
Cancel beside its save; nothing navigates away to add one thing, and the same
form edits an existing record where the record is editable at all — a
credential is not (see Secrets).

Where a list is a configurable panel, the add is part of the draft: the row
lights the frame and Apply is what makes it real, and a record born that way is
born inert — a new VLAN interface is created `disabled`, so adding it changes
nothing until somebody gives it a role. Where the list is not a draft — a
credential, an exit node, a generated key — the add writes at once, and so does the
remove.

Which of the two a list is, is the panel's answer, not the form's: a list inside
a frame stages, a list without one writes. `node_card.tsx` says it for the case
where both meet — the node's fields stage, and removing the node takes effect at
once.

## Confirmation

`useConfirm` is the only way the panel asks. Never `window.confirm`.

The dialog has three parts: a title naming what is about to happen
(`Delete the pool tank`), a body of one or two sentences saying what it costs
with the mechanism first, and the action's own verb on the button. Escape and
the backdrop cancel.

**The body states the concrete consequence, cascades included.** A delete that
clears references says how many and whose: `2 devices lose this key and will
need a new one`. `credentials_page.tsx` composes these from the reference counts
the API returns.

The confirming button is `button--primary` and wears the action's verb; the red
is spent on the button that opened the dialog, not on the one that closes it.

Settings are not confirmed here. A group of them ends in an apply bar, and the
bar's `warning` is where its cost is stated. Deleting data that cannot be
re-derived asks for more than a press: the name typed back, in a red-bordered
box inside the card rather than in this dialog ([visual.md](visual.md)).

## Drawers and modals

A **drawer** is the detail view of one record from a list. It pins to the right
edge at full height, portals to `document.body` so no stacking context can put
it under the top bar, dismisses on Escape or the backdrop, and defers its own
loading until it opens by passing a null path to `useApiResource`.
`device_drawer.tsx` is the reference, and a list page therefore never navigates
away to show one row.

A drawer is one record, so it saves as one record: sections down the body, one
`button--commit` at the foot, and no apply bars. Actions that are not part of
that record — reboot, wake, install — act at once from their own row, and their
output streams into the log at the bottom.

A **modal** is for one interaction that must finish before anything else: a
confirmation, a terminal session, a file transfer, an install consent. Anything
that is merely detail is a drawer. Every modal closes on Escape, closing only
itself — the layer underneath stays — and one that tells the reader so must
mean it. The exception is a modal that captures the keyboard: a terminal's
Escape belongs to the shell, the way every established terminal works, and its
hint names the close button instead.

## Secrets

A secret the hub is **given** is write-only: typed once, listed back as metadata
— name, fingerprint, reference count, when it was last used — and never shown
again. The field for one stands empty behind `PRIVATE_KEY_PLACEHOLDER`, which is
deliberately a template so nothing reads as stored key material.

A secret the hub **generates** is shown to its owner: masked by default, with
`Reveal` / `Hide` and a copy button beside it.

**A credential is never edited** — not its value, not its name. It is added,
referenced, and deleted, the way a token works on GitHub: replacing one is
adding a new credential, pointing its consumers at it, and deleting the old
one, whose dialog words the cascade
([architecture.md](architecture.md), "The credential vault"). A stored value
is never read back into a field for any purpose.

A copy button goes through `copyText`, which falls back to a selection because
the panel is served over plain HTTP and the clipboard API is absent there. It
confirms in place, swapping to a check and `Copied` for a moment, because a copy
that looks like nothing happened gets pressed again.

## Journals and streamed output

Output a person reads goes into the page — a journal panel, or the log at the
bottom of a drawer. Nothing in this panel is announced in a toast and dismissed;
an install is a thing you read.

A journal is a fixed tail of the last 200 lines, fetched only while it is open —
a services page with eight units pulls no journals until somebody asks for one —
and while open it polls itself and scrolls to the newest line, like every other
live panel. `ai_journal_panel.tsx` is the reference.

A task that is running streams into the same place through `useTaskStream`,
which caps at 2000 lines, replays from line one when the socket comes back, and
gives up after one reconnect. Anything a shell wrote goes through `stripAnsi`
before it is rendered.

## Empty states and loading

While a page's first load is in flight it shows a `skeleton` roughly the height
of what will land. A `Spinner` is for work somebody started and is waiting on —
inside the button that started it, or beside the row it is working on. A page
never loads behind a spinner.

An empty list is a `placeholder` with two lines: what is missing, then how to
fill it, and the button that fills it where one exists. `No nodes configured` /
`Add one with a share link from your provider.`

## Notices and errors

A failure renders in place. An inline `notice--error` where an action failed, an
`ErrorPanel` with a Retry where a load failed — never a blank page, because the
panel is most needed exactly when the box is unwell. A failed poll keeps the
last good value on screen and the next tick retries.

The backend returns `{code, params}` and the frontend words it, from a map
beside the component that shows it — `install_consent_modal.tsx`,
`settings_page.tsx` (`RESTORE_ERROR_SENTENCES`) and `services_page.tsx`
(`DECLARED_INVALID_WORDING`) are the shape. An unworded code drops an optional
detail, but never a consequence somebody is being asked to accept: that one
still shows, with the code spelled out, because an unworded consequence beats a
hidden one.

Not every endpoint has a code yet, and `describeError` falls through to the
backend's own sentence where none came. Adding a code is what moves a message
off that path ([ui_text.md](ui_text.md), "Localization"), and what the sentence
says once it is there is the same page.

## Nothing asks for a refresh

No screen in this panel may require a manual page reload, and no panel carries a
refresh button. A panel showing live state polls itself — and does not announce
it: self-refresh is the whole panel's default, and a `live` dot or badge every
panel would wear marks nothing, so none wears one. A pulsing dot belongs only
to a state word that is really being reported (`running`, `answering`, the
strip's own `live` / `connecting` / `offline`). When the process behind the
panel changes, the page reloads itself
([architecture.md](architecture.md), "The panel heals itself").

A Retry on a failed load is not a refresh: it is the way out of an error state,
and it exists only while the error is on screen.

A cadence is a named constant at the top of the file, never a literal at the
call site, and it slows to nothing while the tab is hidden — `document.hidden`
gates the tick, because a background tab polling the gateway every second buys
nobody anything.

| Interval | For |
| --- | --- |
| 15 s (`DEFAULT_POLL_INTERVAL_MS`) | Anything with no reason to be faster |
| 5–10 s | A list or a badge that changes on its own — services, devices, pools |
| 1–3 s | Something a person is watching change right now |
| 500–700 ms | A step in flight with an end: a port move, the setup wizard |
| socket | Where the reading is the point: stats, DNS log, a terminal |

The panel identity probe is fixed at 3 s and is not a resource poll
(`panel_identity.ts`).

## When an effect happens

| Kind | When it acts |
| --- | --- |
| Visualizing panel | On its own, every tick, with no action from anybody |
| Configurable panel | On its apply, never on a keystroke |
| A revocation — deleting a key, a token, a credential, a device | At once; the confirm dialog is the whole of the delay |
| Expensive or rude work — a LAN scan | Only on an explicit press |

A revocation never waits behind an apply bar. What else waits is what a frame
stages, and nothing else does.

## The words live at the top of the file

Every string a person reads is a `const` above the component that shows it —
one `WORDING` table, or named constants where a section owns a family of them
(`ai_page.tsx`, `services_page.tsx`). Nothing user-visible is written inline in
JSX. Several older pages still hold their strings in the markup; moving a
file's copy to the top is part of touching that file, not a separate errand.

Counts and names go in through placeholders — `{healthy} of {total} reachable` —
rather than concatenation, because a sentence assembled from fragments has an
English word order baked into it ([ui_text.md](ui_text.md), "Localization").

## An interaction this document does not cover

Before designing one, establish that it is not generic. **Where an established
website or app already has this feature, follow its logic** rather than
inventing another, and name the app you followed in the summary of the change.
Most interactions somebody reaches for here — a filter row, a detail drawer, a
masked secret, a confirm-before-delete — already exist above, and a third idiom
for a thing that has one is worse than a plain copy of it.

Only a genuinely novel interaction is a decision, and it is the user's: ask
before building it, not after.

# icons

The Neutrino mark: a gradient N on the panel's own background, `#0a0e14`,
rounded the way an application icon is. The one icon source: the hub and
agent packaging builds copy what they ship from here.

`neutrino.png` is the source at 1254×1254. The numbered files beside it are
rendered from it at the sizes packaging asks for — desktop entries want 48 and
256, Windows wants 16 through 256, macOS wants 512.

Regenerate them all from the source rather than editing one by hand; the
originals live in `images/original/`.

# icons

The Neutrino mark: a gradient N on the panel's own background, `#0a0e14`,
rounded the way an application icon is. The one icon source: the hub and
agent packaging builds copy what they ship from here.

`neutrino.png` is the source at 1254×1254. The numbered files beside it are
rendered from it at the sizes packaging asks for — desktop entries want 48 and
256, Windows wants 16 through 256, macOS wants 512.

Regenerate them all from the source rather than editing one by hand; the
originals live in `images/original/`.

`neutrino_hub.png` and its sizes are the hub's application entry: the same
mark on its square, with the square's edge in the panel's accent and a
glow around it, the way the panel's own brand box looks. The client's
entry keeps the plain mark. `render_hub_icons.py` draws them from
`neutrino.png` with Pillow.

`neutrino_ios.png` is the iOS app's icon at 1024×1024: the same mark with
`#0a0e14` filling the whole square, opaque and with square corners, since
iOS fills transparent pixels and rounds the corners itself.
`render_ios_icon.py` draws it from `neutrino.png` with Pillow, and
`packaging/build/build_client_ios.py` puts it into the app.

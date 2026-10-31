# icons

The source of every icon Neutrino ships: the wolf's faces and the device modules' glyphs. Packaging, the panel and the Web share page read them at build time.

| Folder | Holds |
| --- | --- |
| `neutrino_hub/` | The hub's eight faces, with a coloured ring around the whole edge. `angry` is red on black. |
| `neutrino_client/` | The client's seven faces, with colour at the top left and bottom right corners alone. The Web share page and both phone apps use this family. |
| `modules/` | One glyph per device module. |

## The files of a face

| File | Used for |
| --- | --- |
| `wolf_<face>.svg` | A page that draws the face, at any size. |
| `wolf_<face>_1024.png` | The transparent large file. `packaging/shared/icons.py` scales it down to every size from 32 px up, at build time. |
| `wolf_<face>_16.png` | The hand-drawn file, used unchanged at 16 px. A `.ico` and a `.icns` hold it beside the larger sizes. |

## Which face is for what

| Face | Hub | Client | Web share page |
| --- | --- | --- | --- |
| `open` | the application icon, `.ico`, `.icns`, sidebar, login and favicon | none | none |
| `wink` | none | the application icon, `.ico`, `.icns`, window, tray, and the iOS and Android app icons | the introduction and its tab icon |
| `waiting` | the session check | the tray while connecting | loading |
| `sleep` | none | the tray with no hub joined, or disconnected | the hub is offline |
| `error` | none | the tray when a hub cannot be reached | the app is unavailable |
| `sad` | the not-found page | none | the link no longer works, and the link is incomplete |
| `happy` | the setup's finished page | none | none |
| `angry` | the login page's lockdown | none | none |

## Where the faces come from

`scenes/home_hero/scripts/wolf_expressions.py` in the `neutrino-public-image` repository draws every face. A changed face is drawn there and copied here whole, its three files together.

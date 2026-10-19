import SwiftUI

/// The root of every page: the palette the chosen theme and the phone's appearance give, and the words of the
/// chosen language.
struct ThemedRoot: View {
    @ObservedObject var core: ClientCore

    /// The views of every terminal tab.
    let cache: TerminalViewCache

    var body: some View {
        ThemedShell(core: core, cache: cache)
            .preferredColorScheme(scheme)
    }

    private var scheme: ColorScheme? {
        switch core.settings.theme {
        case "dark": return .dark
        case "light": return .light
        default: return nil
        }
    }
}

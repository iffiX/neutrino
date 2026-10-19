import SwiftUI

/// The shell in the palette of the appearance in force.
struct ThemedShell: View {
    @ObservedObject var core: ClientCore

    /// The views of every terminal tab.
    let cache: TerminalViewCache

    @Environment(\.colorScheme) private var colorScheme

    var body: some View {
        AppShell(core: core, cache: cache)
            .environment(\.palette, colorScheme == .dark ? .dark : .light)
            .environment(\.words, core.words)
    }
}

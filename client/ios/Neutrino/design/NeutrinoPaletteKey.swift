import SwiftUI

/// The palette a view draws in, set once at the root by the theme the person chose.
struct NeutrinoPaletteKey: EnvironmentKey {
    static let defaultValue = NeutrinoPalette.dark
}

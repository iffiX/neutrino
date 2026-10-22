import SwiftUI

extension EnvironmentValues {
    /// The palette a view draws in.
    var palette: NeutrinoPalette {
        get { self[NeutrinoPaletteKey.self] }
        set { self[NeutrinoPaletteKey.self] = newValue }
    }

    /// The sentences a view words itself with.
    var words: WordCatalog {
        get { self[WordCatalogKey.self] }
        set { self[WordCatalogKey.self] = newValue }
    }

    /// Whether the shell draws the sidebar, so a page's own action is in the page header and not in the page.
    var isSidebar: Bool {
        get { self[SidebarLayoutKey.self] }
        set { self[SidebarLayoutKey.self] = newValue }
    }
}

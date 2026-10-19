import Foundation

/// A page the app shows, with the words of its title and the icon of its bar entry.
enum AppScreen: String, CaseIterable, Identifiable {
    case hubs
    case web
    case files
    case terminals
    case settings
    case join

    /// The pages in the bar, in the order the bars draw them.
    static let tabs: [AppScreen] = [.hubs, .web, .files, .terminals, .settings]

    /// The page's name, as a list keys it.
    var id: String { rawValue }

    /// The catalog key of its title.
    var titleKey: String {
        switch self {
        case .hubs: return "ui.section_hubs"
        case .web: return "ui.panel_web"
        case .files: return "ui.panel_files"
        case .terminals: return "ui.panel_terminals"
        case .settings: return "ui.settings"
        case .join: return "ui.add_hub"
        }
    }

    /// The SF Symbol of its bar entry.
    var systemImage: String {
        switch self {
        case .hubs: return "server.rack"
        case .web: return "globe"
        case .files: return "folder"
        case .terminals: return "terminal"
        case .settings: return "gearshape"
        case .join: return "plus"
        }
    }

    /// The bar entry a page reached from another page belongs to, for its back arrow; nil for a bar page.
    var parent: AppScreen? { self == .join ? .hubs : nil }
}

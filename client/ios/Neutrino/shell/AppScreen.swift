import Foundation

/// A page the app shows, with the words of its title and of its bar entry and the icon of its bar entry.
enum AppScreen: String, CaseIterable, Identifiable {
    case hubs
    case apps
    case files
    case terminals
    case desktops
    case settings
    case join

    /// The pages in the bar, in the order the bars draw them.
    static let tabs: [AppScreen] = [.hubs, .apps, .files, .terminals, .desktops, .settings]

    /// The page's name, as a list keys it.
    var id: String { rawValue }

    /// The catalog key of its title.
    var titleKey: String {
        switch self {
        case .hubs: return "ui.section_hubs"
        case .apps: return "ui.panel_apps"
        case .files: return "ui.panel_files"
        case .terminals: return "ui.panel_terminals"
        case .desktops: return "ui.panel_desktops"
        case .settings: return "ui.settings"
        case .join: return "ui.add_hub"
        }
    }

    /// The catalog key of its bar entry: the title, shortened where six entries share a phone's bar.
    var barKey: String { self == .desktops ? "ui.bar_desktops" : titleKey }

    /// The SF Symbol of its bar entry; the bars draw Remote desktops' monitor themselves.
    var systemImage: String {
        switch self {
        case .hubs: return "server.rack"
        case .apps: return "square.grid.2x2"
        case .files: return "folder"
        case .terminals: return "terminal"
        case .desktops: return "display"
        case .settings: return "gearshape"
        case .join: return "plus"
        }
    }

    /// The bar entry a page reached from another page belongs to, for its back arrow; nil for a bar page.
    var parent: AppScreen? { self == .join ? .hubs : nil }
}

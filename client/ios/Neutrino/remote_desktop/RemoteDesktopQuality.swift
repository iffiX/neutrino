import Foundation

/// The picture quality a remote desktop session asks for, as RustDesk's `image-quality` names it.
enum RemoteDesktopQuality: String, CaseIterable, Identifiable {
    /// RustDesk's default trade between the picture and the bandwidth.
    case balanced

    /// Fewer bits per frame for a slow network.
    case low

    /// The best picture the network carries.
    case best

    /// The option's value in the core.
    var coreName: String { rawValue }

    /// The catalog key the picker shows.
    var wordKey: String { "ui.rdp_quality_\(rawValue)" }

    /// The quality's core name, as a list keys it.
    var id: String { rawValue }

    /// A quality by its core name.
    ///
    /// - Parameter coreName: The name kept in the settings.
    /// - Returns: The quality, or `balanced` for a name the app does not know.
    static func of(_ coreName: String) -> RemoteDesktopQuality {
        RemoteDesktopQuality(rawValue: coreName) ?? .balanced
    }
}

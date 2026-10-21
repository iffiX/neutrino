import Foundation

/// The codec a remote desktop session asks the machine to send, as RustDesk's `codec-preference` names it: Auto and
/// the three codecs the iOS core offers.
enum RemoteDesktopCodec: String, CaseIterable, Identifiable {
    /// The machine and the core agree on one.
    case auto

    /// libvpx's VP8.
    case vp8

    /// libvpx's VP9.
    case vp9

    /// libaom's AV1.
    case av1

    /// The option's value in the core.
    var coreName: String { rawValue }

    /// What the picker shows; empty for `auto`, which the catalog words.
    var title: String {
        self == .auto ? "" : rawValue.uppercased()
    }

    /// The codec's core name, as a list keys it.
    var id: String { rawValue }

    /// A codec by its core name.
    ///
    /// - Parameter coreName: The name kept in the settings.
    /// - Returns: The codec, or `auto` for a name the app does not know.
    static func of(_ coreName: String) -> RemoteDesktopCodec {
        RemoteDesktopCodec(rawValue: coreName) ?? .auto
    }
}

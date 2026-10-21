import Foundation

/// What the Configure sheet of one shared desktop keeps for its next Connect.
struct RemoteDesktopChoice: Equatable {
    /// The codec asked of the machine.
    var codec = RemoteDesktopCodec.auto

    /// The picture quality asked for.
    var quality = RemoteDesktopQuality.balanced

    /// The core's session options this choice sets, by RustDesk's names: `codec-preference` and `image-quality`.
    var options: [(String, String)] {
        [(RemoteDesktop.optionCodec, codec.coreName), (RemoteDesktop.optionQuality, quality.coreName)]
    }
}

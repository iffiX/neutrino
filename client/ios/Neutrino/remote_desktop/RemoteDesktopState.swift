import Foundation

/// Where a viewer's connection stands.
enum RemoteDesktopState: Equatable {
    /// The core is reaching the machine.
    case connecting

    /// The core hands the machine's screen to the viewer.
    case showing

    /// The viewer shows no picture: the core's refusal, or `rdp_core_missing` while no core is built in.
    case stopped(ClientError)
}

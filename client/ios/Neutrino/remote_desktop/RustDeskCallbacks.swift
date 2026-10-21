import Foundation

/// What the RustDesk core reports, called on its own threads.
struct RustDeskCallbacks {
    /// The connection changed: one of the `RemoteDesktop.state` constants, and why it ended in RustDesk's words,
    /// empty otherwise.
    let onState: (Int, String) -> Void

    /// The remote picture has a new width and height, in pixels.
    let onSize: (Int, Int) -> Void

    /// Text was copied on the remote machine.
    let onClipboard: (String) -> Void
}

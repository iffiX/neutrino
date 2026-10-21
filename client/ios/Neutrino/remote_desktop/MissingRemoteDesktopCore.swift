import Foundation

/// The core when this build carries none, as on the Simulator: every connection stops at once with
/// `rdp_core_missing`.
final class MissingRemoteDesktopCore: RemoteDesktopCore {
    func connect(
        target: RemoteDesktopTarget, onState: @escaping (RemoteDesktopState) -> Void,
        onFrameSize: @escaping (Int, Int) -> Void, onClipboard: @escaping (String) -> Void
    ) {
        onState(.stopped(.refusal("rdp_core_missing")))
    }

    func attach(_ sink: RemoteDesktopFrameSink?) {}

    func mouse(_ event: RemoteDesktopMouse) {}

    func key(_ code: String, isDown: Bool) {}

    func type(_ text: String) {}

    func clipboard(_ text: String) {}

    func disconnect() {}
}

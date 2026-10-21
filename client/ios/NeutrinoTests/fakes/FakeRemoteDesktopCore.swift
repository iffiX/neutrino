import Foundation

@testable import Neutrino

/// A core that records what the viewer sends it, and reports the states a test hands it.
final class FakeRemoteDesktopCore: RemoteDesktopCore {
    /// Every key, text and clipboard call, in order.
    var calls: [String] = []

    /// Every mouse event, in order.
    var mice: [RemoteDesktopMouse] = []

    /// The targets connected to, in order.
    var targets: [RemoteDesktopTarget] = []

    /// How many times the connection was closed.
    var disconnects = 0

    /// Whether a sink is attached.
    var isAttached = false

    private var onState: ((RemoteDesktopState) -> Void)?

    func connect(
        target: RemoteDesktopTarget, onState: @escaping (RemoteDesktopState) -> Void,
        onFrameSize: @escaping (Int, Int) -> Void, onClipboard: @escaping (String) -> Void
    ) {
        targets.append(target)
        self.onState = onState
    }

    func attach(_ sink: RemoteDesktopFrameSink?) {
        isAttached = sink != nil
    }

    func mouse(_ event: RemoteDesktopMouse) {
        mice.append(event)
    }

    func key(_ code: String, isDown: Bool) {
        calls.append("key \(code) \(isDown ? "down" : "up")")
    }

    func type(_ text: String) {
        calls.append("text \(text)")
    }

    func clipboard(_ text: String) {
        calls.append("clipboard \(text)")
    }

    func disconnect() {
        disconnects += 1
    }

    /// Report a state to the viewer that connected.
    ///
    /// - Parameter state: The state.
    func report(_ state: RemoteDesktopState) {
        onState?(state)
    }
}

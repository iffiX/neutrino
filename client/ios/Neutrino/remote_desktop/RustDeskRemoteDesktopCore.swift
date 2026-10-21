import Foundation

/// The RustDesk core a device build links: one direct session at a time, its frames handed to the viewer's sink.
/// Call it on the main queue.
final class RustDeskRemoteDesktopCore: RemoteDesktopCore {
    private static var isInitialized = false

    private let appDir: String
    private var state = RemoteDesktopState.connecting
    private var session = 0
    private var isRunning = false

    /// Make the core.
    ///
    /// - Parameter appDir: Where the core keeps its configuration.
    init(appDir: String) {
        self.appDir = appDir
    }

    func connect(
        target: RemoteDesktopTarget, onState: @escaping (RemoteDesktopState) -> Void,
        onFrameSize: @escaping (Int, Int) -> Void, onClipboard: @escaping (String) -> Void
    ) {
        if isRunning { disconnect() }
        if !Self.isInitialized {
            RustDeskNative.initialize(appDir: appDir)
            Self.isInitialized = true
        }
        session += 1
        let current = session
        state = .connecting
        isRunning = true
        let callbacks = RustDeskCallbacks(
            onState: { [weak self] report, text in
                DispatchQueue.main.async {
                    guard let self, current == self.session else { return }
                    self.advance(Self.next(self.state, report: report, text: text), onState)
                }
            },
            onSize: { [weak self] width, height in
                DispatchQueue.main.async {
                    guard let self, current == self.session, self.isRunning else { return }
                    onFrameSize(width, height)
                }
            },
            onClipboard: { [weak self] text in
                DispatchQueue.main.async {
                    guard let self, current == self.session, self.isRunning else { return }
                    onClipboard(text)
                }
            })
        for (name, value) in target.choice.options { RustDeskNative.setOption(name, value) }
        let started = RustDeskNative.start(
            peer: target.host, port: target.port, password: target.password, callbacks: callbacks)
        if started != 0 {
            advance(.stopped(.refusal("rdp_launch_failed", ["detail": "\(started)"])), onState)
        }
    }

    func attach(_ sink: RemoteDesktopFrameSink?) {
        RustDeskNative.attachFrames(sink)
    }

    func mouse(_ event: RemoteDesktopMouse) {
        if isRunning { RustDeskNative.mouse(event) }
    }

    func key(_ code: String, isDown: Bool) {
        if isRunning { RustDeskNative.key(code, isDown: isDown) }
    }

    func type(_ text: String) {
        if isRunning { RustDeskNative.text(text) }
    }

    func clipboard(_ text: String) {
        if isRunning { RustDeskNative.clipboard(text) }
    }

    func disconnect() {
        session += 1
        guard isRunning else { return }
        isRunning = false
        RustDeskNative.close()
    }

    /// Where a connection stands after one report of the core.
    ///
    /// - Parameters:
    ///   - current: Where it stood.
    ///   - report: The core's report, one of the `RemoteDesktop.state` constants.
    ///   - text: Why it ended, in RustDesk's words.
    /// - Returns: The new standing; a stopped connection stays stopped.
    static func next(_ current: RemoteDesktopState, report: Int, text: String) -> RemoteDesktopState {
        if case .stopped = current { return current }
        switch report {
        case RemoteDesktop.stateConnected: return .showing
        case RemoteDesktop.stateLoginFailed: return .stopped(.refusal("rdp_login_failed"))
        case RemoteDesktop.stateClosed: return .stopped(.refusal("rdp_closed", ["reason": text]))
        default: return current
        }
    }

    private func advance(_ next: RemoteDesktopState, _ onState: (RemoteDesktopState) -> Void) {
        guard isRunning, next != state else { return }
        state = next
        if case .stopped = next {
            isRunning = false
            RustDeskNative.close()
        }
        onState(next)
    }
}

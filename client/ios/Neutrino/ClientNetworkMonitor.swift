import Foundation
import Network

/// The phone's connectivity: whether it has a network at all, and every change of its paths, a VPN another app
/// connects or disconnects among them.
final class ClientNetworkMonitor {
    private let monitor = NWPathMonitor()
    private var lastPath: NWPath?

    /// Called on the main queue after each change of the phone's paths.
    var onChange: (() -> Void)?

    /// Whether the phone has a network at all.
    private(set) var hasNetwork = true

    /// Start watching.
    func start() {
        monitor.pathUpdateHandler = { [weak self] path in
            DispatchQueue.main.async { self?.take(path) }
        }
        monitor.start(queue: DispatchQueue.global(qos: .utility))
    }

    private func take(_ path: NWPath) {
        hasNetwork = path.status == .satisfied
        defer { lastPath = path }
        guard let lastPath, lastPath != path else { return }
        onChange?()
    }
}

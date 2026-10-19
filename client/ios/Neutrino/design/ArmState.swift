import Combine
import Foundation

/// Which destructive button is armed, app-wide: one at a time, for five seconds.
final class ArmState: ObservableObject {
    /// The key of the armed button, nil for none.
    @Published private(set) var armed: String?

    private var timer: DispatchWorkItem?

    /// Arm one button; any other disarms.
    ///
    /// - Parameter key: The button's key.
    func arm(_ key: String) {
        armed = key
        timer?.cancel()
        let item = DispatchWorkItem { [weak self] in
            if self?.armed == key { self?.armed = nil }
        }
        timer = item
        DispatchQueue.main.asyncAfter(deadline: .now() + Client.armSeconds, execute: item)
    }

    /// Disarm whatever is armed.
    func disarm() {
        timer?.cancel()
        timer = nil
        armed = nil
    }
}

import Foundation

@testable import Neutrino

/// A timer of `FakeClientClock`.
final class FakeClientTimer: ClientTimer {
    let at: Double
    let order: Int
    let action: () -> Void
    private(set) var isCancelled = false

    init(at: Double, order: Int, action: @escaping () -> Void) {
        self.at = at
        self.order = order
        self.action = action
    }

    func cancel() {
        isCancelled = true
    }
}

import Foundation

@testable import Neutrino

/// A clock a test moves by hand: its timers run, in order, only when the test advances it.
final class FakeClientClock: ClientClock {
    private var timers: [FakeClientTimer] = []
    private var order = 0

    /// The wall time, in seconds.
    private(set) var now: Double = 1_000_000

    /// The monotonic time, in nanoseconds.
    private(set) var uptimeNanos: UInt64 = 1_000_000_000

    @discardableResult
    func schedule(after seconds: Double, _ action: @escaping () -> Void) -> ClientTimer {
        order += 1
        let timer = FakeClientTimer(at: now + max(seconds, 0), order: order, action: action)
        timers.append(timer)
        return timer
    }

    /// Move the time forward, running every timer that falls due on the way.
    ///
    /// - Parameter seconds: How far.
    func advance(by seconds: Double) {
        let end = now + seconds
        while let next = timers.filter({ !$0.isCancelled && $0.at <= end }).min(by: {
            ($0.at, $0.order) < ($1.at, $1.order)
        }) {
            move(to: next.at)
            timers.removeAll { $0 === next }
            next.action()
        }
        move(to: end)
        timers.removeAll { $0.isCancelled }
    }

    /// How many timers wait to run.
    var pendingCount: Int { timers.filter { !$0.isCancelled }.count }

    private func move(to time: Double) {
        guard time > now else { return }
        uptimeNanos += UInt64((time - now) * 1e9)
        now = time
    }
}

import Foundation

/// The phone's own time, with timers on the main queue.
final class SystemClientClock: ClientClock {
    var now: Double { Date().timeIntervalSince1970 }

    var uptimeNanos: UInt64 { DispatchTime.now().uptimeNanoseconds }

    @discardableResult
    func schedule(after seconds: Double, _ action: @escaping () -> Void) -> ClientTimer {
        let item = DispatchWorkItem(block: action)
        DispatchQueue.main.asyncAfter(deadline: .now() + max(seconds, 0), execute: item)
        return SystemClientTimer(item: item)
    }
}

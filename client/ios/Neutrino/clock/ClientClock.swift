import Foundation

/// The time and the timers the app core runs on; every timer fires on the main queue.
protocol ClientClock: AnyObject {
    /// The wall time, in seconds since 1970, as a countdown on a page is drawn against.
    var now: Double { get }

    /// A monotonic time in nanoseconds, by which openings and round trips are measured.
    var uptimeNanos: UInt64 { get }

    /// Run an action once, after a delay.
    ///
    /// - Parameters:
    ///   - seconds: The delay.
    ///   - action: What runs.
    /// - Returns: The timer, to cancel.
    @discardableResult
    func schedule(after seconds: Double, _ action: @escaping () -> Void) -> ClientTimer
}

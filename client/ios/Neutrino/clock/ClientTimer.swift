import Foundation

/// One scheduled action of a `ClientClock`.
protocol ClientTimer: AnyObject {
    /// Keep the action from running; a timer that already ran is unchanged.
    func cancel()
}

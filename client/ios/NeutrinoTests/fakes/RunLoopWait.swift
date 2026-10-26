import Foundation

/// Turns the main run loop in a test, so the main queue's sockets and blocks run.
enum RunLoopWait {
    /// Turn the main run loop until a condition holds.
    ///
    /// - Parameters:
    ///   - seconds: How long at most.
    ///   - condition: What is waited for.
    /// - Returns: Whether it held in time.
    @discardableResult
    static func until(seconds: Double = 5, _ condition: () -> Bool) -> Bool {
        let end = Date().addingTimeInterval(seconds)
        while !condition() {
            if Date() >= end { return false }
            RunLoop.main.run(until: Date().addingTimeInterval(0.01))
        }
        return true
    }

    /// Turn the main run loop for a while.
    ///
    /// - Parameter seconds: How long.
    static func turn(seconds: Double = 0.2) {
        RunLoop.main.run(until: Date().addingTimeInterval(seconds))
    }
}

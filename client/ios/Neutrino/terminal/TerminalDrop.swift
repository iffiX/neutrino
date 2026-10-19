import Foundation

/// The dropping a Clear started on one tab: since when, and when the last output arrived.
final class TerminalDrop {
    /// When the Clear was pressed, in wall seconds.
    let since: Double

    /// When the last output was dropped, in wall seconds.
    var last: Double

    /// Start dropping.
    ///
    /// - Parameters:
    ///   - since: When the Clear was pressed.
    ///   - last: When the last output arrived.
    init(since: Double, last: Double) {
        self.since = since
        self.last = last
    }

    /// When the dropping ends: half a second after the last output, twenty seconds after the Clear at most.
    var endsAt: Double {
        min(last + TerminalPage.clearQuietSeconds, since + TerminalPage.clearMaxSeconds)
    }
}

import Foundation

/// A timer of `SystemClientClock`, on the main queue.
final class SystemClientTimer: ClientTimer {
    private let item: DispatchWorkItem

    /// Wrap a scheduled work item.
    ///
    /// - Parameter item: The work item on the main queue.
    init(item: DispatchWorkItem) {
        self.item = item
    }

    func cancel() {
        item.cancel()
    }
}

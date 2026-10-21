import Foundation

/// The stop of one transfer: set on the main queue by Cancel, read by the SMB client on its own queue before each
/// next part.
final class ShareCancel {
    private let lock = NSLock()
    private var isSet = false

    /// Whether Cancel stopped the transfer.
    var isCancelled: Bool {
        lock.lock()
        defer { lock.unlock() }
        return isSet
    }

    /// Stop the transfer at its next part.
    func cancel() {
        lock.lock()
        isSet = true
        lock.unlock()
    }
}

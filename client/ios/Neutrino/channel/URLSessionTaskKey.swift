import Foundation

/// The key of a data task, set once the task exists, for its own completion to read.
final class URLSessionTaskKey {
    /// The task's identity; nil until it is created.
    var key: ObjectIdentifier?
}

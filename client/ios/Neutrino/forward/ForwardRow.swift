import Foundation

/// What one app's row, or a hub's panel, shows of its forwards.
struct ForwardRow: Equatable {
    /// Whether the app is in use: from the first forward Use made until Stop.
    var isInUse = false

    /// The loopback number the panel's forward listens on, 0 while it has none.
    var localPort = 0

    /// Whether a job runs on the row: Use or Panel, or Stop.
    var job: ForwardJob?

    /// The code the row's last job ended in, until its next press or a refresh.
    var error: ClientError?
}

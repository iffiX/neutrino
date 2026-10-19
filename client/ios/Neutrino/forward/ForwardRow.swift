import Foundation

/// What one entry's row shows of its forward.
struct ForwardRow: Equatable {
    /// The loopback number it listens on, 0 while not forwarded.
    var localPort = 0

    /// Whether a job runs on the row: Open, or Disconnect.
    var job: ForwardJob?

    /// The code the row's last job ended in, until its next press or a refresh.
    var error: ClientError?

    /// Whether the loopback listens.
    var isForwarded: Bool { localPort != 0 }
}

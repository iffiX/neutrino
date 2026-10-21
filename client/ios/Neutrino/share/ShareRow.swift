import Foundation

/// What a file entry's row on the Files page shows of Open.
struct ShareRow: Equatable {
    /// Whether Open, or Connect in the login sheet, is logging in.
    var isOpening = false

    /// The code the row's last Open ended in, until its next press or a refresh.
    var error: ClientError?
}

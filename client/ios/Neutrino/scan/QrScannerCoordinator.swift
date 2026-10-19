import Foundation

/// What the scanner's view remembers between updates: the scan it last started.
final class QrScannerCoordinator {
    /// The press of Scan the scanner last answered.
    var scanCount: Int

    /// Remember the first scan.
    ///
    /// - Parameter scanCount: The press it answers.
    init(scanCount: Int) {
        self.scanCount = scanCount
    }
}

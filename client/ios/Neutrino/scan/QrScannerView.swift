import SwiftUI

/// The camera's picture on the Join page; a change of `scanCount` looks for a code again.
struct QrScannerView: UIViewControllerRepresentable {
    /// How many times Scan was pressed; each press after a taken code scans again.
    let scanCount: Int

    /// Called once per scan with the text of the QR code seen.
    let onCode: (String) -> Void

    func makeCoordinator() -> QrScannerCoordinator {
        QrScannerCoordinator(scanCount: scanCount)
    }

    func makeUIViewController(context: Context) -> QrScanController {
        let controller = QrScanController()
        controller.onCode = onCode
        return controller
    }

    func updateUIViewController(_ controller: QrScanController, context: Context) {
        controller.onCode = onCode
        if context.coordinator.scanCount != scanCount {
            context.coordinator.scanCount = scanCount
            controller.rescan()
        }
    }
}

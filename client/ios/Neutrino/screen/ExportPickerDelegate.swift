import UIKit

/// The export picker's delegate: it reports the picker's end, a saved copy or a cancel alike.
final class ExportPickerDelegate: NSObject, UIDocumentPickerDelegate {
    /// Called once the picker ends.
    var onEnd: () -> Void

    /// Report the picker's end.
    ///
    /// - Parameter onEnd: Called once the picker ends.
    init(onEnd: @escaping () -> Void) {
        self.onEnd = onEnd
    }

    func documentPicker(_ controller: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) {
        onEnd()
    }

    func documentPickerWasCancelled(_ controller: UIDocumentPickerViewController) {
        onEnd()
    }
}

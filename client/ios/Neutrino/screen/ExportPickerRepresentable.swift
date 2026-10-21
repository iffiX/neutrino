import SwiftUI
import UIKit

/// The system's export picker for Save to Files: it saves a copy of one local file where the person chooses.
struct ExportPickerRepresentable: UIViewControllerRepresentable {
    /// The local file.
    let url: URL

    /// Called once the picker saved the copy or was cancelled.
    let onEnd: () -> Void

    func makeCoordinator() -> ExportPickerDelegate {
        ExportPickerDelegate(onEnd: onEnd)
    }

    func makeUIViewController(context: Context) -> UIDocumentPickerViewController {
        let picker = UIDocumentPickerViewController(forExporting: [url], asCopy: true)
        picker.delegate = context.coordinator
        return picker
    }

    func updateUIViewController(_ picker: UIDocumentPickerViewController, context: Context) {
        context.coordinator.onEnd = onEnd
    }
}

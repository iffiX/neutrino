import PhotosUI
import SwiftUI

/// The system's photo picker for Upload from Photos: photos and videos, several at once, each as its original.
/// It runs outside the app and needs no access to the photo library.
struct PhotoPickerRepresentable: UIViewControllerRepresentable {
    /// Called once the picker ends, with the picked items' providers; empty when cancelled.
    let onPick: ([NSItemProvider]) -> Void

    func makeCoordinator() -> PhotoPickerDelegate {
        PhotoPickerDelegate(onPick: onPick)
    }

    func makeUIViewController(context: Context) -> PHPickerViewController {
        var configuration = PHPickerConfiguration()
        configuration.filter = .any(of: [.images, .videos])
        configuration.selectionLimit = 0
        configuration.preferredAssetRepresentationMode = .current
        let picker = PHPickerViewController(configuration: configuration)
        picker.delegate = context.coordinator
        return picker
    }

    func updateUIViewController(_ picker: PHPickerViewController, context: Context) {
        context.coordinator.onPick = onPick
    }
}

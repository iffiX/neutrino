import PhotosUI

/// The photo picker's delegate: it reports the picker's end with the picked items' providers.
final class PhotoPickerDelegate: NSObject, PHPickerViewControllerDelegate {
    /// Called once the picker ends, with the picked items' providers; empty when cancelled.
    var onPick: ([NSItemProvider]) -> Void

    /// Report the picker's end.
    ///
    /// - Parameter onPick: Called once the picker ends.
    init(onPick: @escaping ([NSItemProvider]) -> Void) {
        self.onPick = onPick
    }

    func picker(_ picker: PHPickerViewController, didFinishPicking results: [PHPickerResult]) {
        onPick(results.map(\.itemProvider))
    }
}

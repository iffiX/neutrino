import Combine
import UIKit

/// The orientation of the app's window scene, followed as the phone turns, which tells on which side of a
/// landscape screen the camera housing is.
final class ShellOrientation: ObservableObject {
    /// The scene's orientation; portrait until a scene is followed.
    @Published private(set) var orientation = UIInterfaceOrientation.portrait

    private var observation: NSKeyValueObservation?

    /// Follow the app's window scene.
    func follow() {
        guard observation == nil,
            let scene = UIApplication.shared.connectedScenes.compactMap({ $0 as? UIWindowScene }).first
        else { return }
        observation = scene.observe(\.effectiveGeometry, options: [.initial, .new]) { [weak self] scene, _ in
            let next = scene.effectiveGeometry.interfaceOrientation
            DispatchQueue.main.async { self?.orientation = next }
        }
    }

    /// Whether the camera housing is at the screen's right: the phone is turned with its top to the right, the
    /// orientation iOS names landscape left.
    ///
    /// - Parameter orientation: The interface orientation.
    /// - Returns: True for landscape left.
    static func isHousingRight(_ orientation: UIInterfaceOrientation) -> Bool {
        orientation == .landscapeLeft
    }
}

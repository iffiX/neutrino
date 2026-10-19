import AVFoundation
import Foundation

/// Whether the app may use the camera, as the Join page draws it.
enum CameraAccess {
    /// The person has not been asked.
    case unasked
    /// The camera may be used.
    case allowed
    /// The person or the phone refused it.
    case refused

    /// The camera's access now.
    static var current: CameraAccess {
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized: return .allowed
        case .notDetermined: return .unasked
        default: return .refused
        }
    }

    /// Ask the person for the camera.
    ///
    /// - Parameter completion: Called on the main queue with the access after the answer.
    static func ask(_ completion: @escaping (CameraAccess) -> Void) {
        AVCaptureDevice.requestAccess(for: .video) { isGranted in
            DispatchQueue.main.async { completion(isGranted ? .allowed : .refused) }
        }
    }
}

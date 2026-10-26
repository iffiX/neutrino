import Foundation

#if canImport(Mobile)
    import Mobile
#endif

/// The transport's gomobile library, `Mobile.xcframework`, linked into a build whose `cores/transport/` holds it.
/// It binds `transport.sock` by a path relative to the process's working directory, which `start` sets to the
/// directory it is given.
final class MobileTransportLibrary: TransportLibrary {
    func start(directory: String, secret: String) throws -> String {
        #if canImport(Mobile)
            guard FileManager.default.changeCurrentDirectoryPath(directory) else {
                throw ClientError.refusal(Transport.codeFailed, ["detail": "no directory \(directory)"])
            }
            var failure: NSError?
            let path = MobileStart(".", secret, &failure)
            if let failure {
                throw ClientError.refusal(Transport.codeFailed, ["detail": failure.localizedDescription])
            }
            return path
        #else
            throw ClientError.refusal(Transport.codeMissing)
        #endif
    }

    func stop() {
        #if canImport(Mobile)
            MobileStop()
        #endif
    }
}

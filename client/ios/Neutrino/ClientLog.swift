import Foundation

#if canImport(os)
    import os
#endif

/// The app's log lines, in the phone's system log under the app's subsystem.
enum ClientLog {
    #if canImport(os)
        private static let logger = Logger(subsystem: Client.logSubsystem, category: "client")
    #endif

    /// Write one line.
    ///
    /// - Parameter text: The line.
    static func info(_ text: String) {
        #if canImport(os)
            logger.info("\(text, privacy: .public)")
        #else
            print(text)
        #endif
    }
}

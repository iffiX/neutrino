import Foundation

/// One item a picker hands over for an upload: it puts its file into a folder of the app's own.
protocol ShareDelivery {
    /// Put the item's file into a folder.
    ///
    /// - Parameters:
    ///   - place: A new folder in the share's temporary directory, made already.
    ///   - completion: Called once, on any queue, with the file in the folder or with the failure.
    func deliver(into place: URL, completion: @escaping (Result<URL, Error>) -> Void)
}

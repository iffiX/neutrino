import Foundation

/// What the share page asks of an SMB client: one connection to one share, at the loopback port of the share's
/// forward. A path is the names from the share's root joined by `/`. A failure is the system's own error,
/// `POSIXError` for what the share answered; every completion and every progress call runs on the main queue.
protocol ShareClient: AnyObject {
    /// Connect to a share and log in.
    ///
    /// - Parameters:
    ///   - port: The loopback port of the share's forward.
    ///   - share: The share's name.
    ///   - login: The account.
    ///   - completion: Called with nil once logged in, or with the failure.
    func connect(port: Int, share: String, login: ShareLogin, completion: @escaping (Error?) -> Void)

    /// The items of one folder, without `.` and `..`.
    ///
    /// - Parameters:
    ///   - path: The folder.
    ///   - completion: Called with the items, in any order, or with the failure.
    func list(_ path: String, completion: @escaping (Result<[ShareItem], Error>) -> Void)

    /// Read a file into a local file, which it replaces.
    ///
    /// - Parameters:
    ///   - path: The file.
    ///   - url: The local file.
    ///   - cancel: Read before each next part; a cancelled read ends with no failure.
    ///   - progress: Called with the bytes read and the file's size.
    ///   - completion: Called with nil once read or cancelled, or with the failure.
    func download(
        _ path: String, to url: URL, cancel: ShareCancel, progress: @escaping (Int64, Int64) -> Void,
        completion: @escaping (Error?) -> Void)

    /// Write a local file as a new file; a name the folder holds fails with `EEXIST`.
    ///
    /// - Parameters:
    ///   - url: The local file.
    ///   - path: The new file.
    ///   - cancel: Read before each next part; a cancelled write ends with no failure and leaves the part written.
    ///   - progress: Called with the bytes written.
    ///   - completion: Called with nil once written or cancelled, or with the failure.
    func upload(
        _ url: URL, to path: String, cancel: ShareCancel, progress: @escaping (Int64) -> Void,
        completion: @escaping (Error?) -> Void)

    /// Make a folder; a name the folder holds fails with `EEXIST`.
    ///
    /// - Parameters:
    ///   - path: The new folder.
    ///   - completion: Called with nil once made, or with the failure.
    func makeFolder(_ path: String, completion: @escaping (Error?) -> Void)

    /// Rename a file or a folder in its folder; a name the folder holds fails with `EEXIST`.
    ///
    /// - Parameters:
    ///   - path: The file or folder.
    ///   - target: Its new path.
    ///   - completion: Called with nil once renamed, or with the failure.
    func move(_ path: String, to target: String, completion: @escaping (Error?) -> Void)

    /// Delete a file, or a folder with everything in it.
    ///
    /// - Parameters:
    ///   - path: The file or folder.
    ///   - isFolder: Whether it is a folder.
    ///   - completion: Called with nil once deleted, or with the failure.
    func remove(_ path: String, isFolder: Bool, completion: @escaping (Error?) -> Void)

    /// Close the connection; a call still running fails.
    func disconnect()
}

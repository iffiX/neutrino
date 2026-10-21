import AMSMB2
import Foundation

/// The share page's SMB client, AMSMB2: one connection to one share at `smb://127.0.0.1:<port>`, SMB2 and SMB3
/// with signing as the server asks. AMSMB2 runs every request on a queue of its own, and each answer is handed
/// to the main queue.
final class SmbShareClient: ShareClient {
    private var manager: SMB2Manager?

    func connect(port: Int, share: String, login: ShareLogin, completion: @escaping (Error?) -> Void) {
        var address = URLComponents()
        address.scheme = "smb"
        address.host = Forward.bindHost
        address.port = port
        let credential = URLCredential(user: login.user, password: login.password, persistence: .forSession)
        guard let url = address.url, let manager = SMB2Manager(url: url, credential: credential) else {
            completion(POSIXError(.EINVAL))
            return
        }
        manager.timeout = SharePage.requestTimeoutSeconds
        self.manager = manager
        manager.connectShare(name: share, encrypted: false) { error in
            DispatchQueue.main.async { completion(error) }
        }
    }

    func list(_ path: String, completion: @escaping (Result<[ShareItem], Error>) -> Void) {
        guard let manager else {
            completion(.failure(POSIXError(.ENOTCONN)))
            return
        }
        manager.contentsOfDirectory(atPath: path, recursive: false) { result in
            let items = result.map { entries in entries.compactMap(Self.item) }
            DispatchQueue.main.async { completion(items) }
        }
    }

    func download(
        _ path: String, to url: URL, cancel: ShareCancel, progress: @escaping (Int64, Int64) -> Void,
        completion: @escaping (Error?) -> Void
    ) {
        guard let manager else {
            completion(POSIXError(.ENOTCONN))
            return
        }
        manager.downloadItem(
            atPath: path, to: url,
            progress: { done, total in
                DispatchQueue.main.async { progress(done, total) }
                return !cancel.isCancelled
            },
            completionHandler: { error in
                DispatchQueue.main.async { completion(error) }
            })
    }

    func upload(
        _ url: URL, to path: String, cancel: ShareCancel, progress: @escaping (Int64) -> Void,
        completion: @escaping (Error?) -> Void
    ) {
        guard let manager else {
            completion(POSIXError(.ENOTCONN))
            return
        }
        manager.uploadItem(
            at: url, toPath: path,
            progress: { done in
                DispatchQueue.main.async { progress(done) }
                return !cancel.isCancelled
            },
            completionHandler: { error in
                DispatchQueue.main.async { completion(error) }
            })
    }

    func makeFolder(_ path: String, completion: @escaping (Error?) -> Void) {
        guard let manager else {
            completion(POSIXError(.ENOTCONN))
            return
        }
        manager.createDirectory(atPath: path) { error in
            DispatchQueue.main.async { completion(error) }
        }
    }

    func move(_ path: String, to target: String, completion: @escaping (Error?) -> Void) {
        guard let manager else {
            completion(POSIXError(.ENOTCONN))
            return
        }
        manager.moveItem(atPath: path, toPath: target) { error in
            DispatchQueue.main.async { completion(error) }
        }
    }

    func remove(_ path: String, isFolder: Bool, completion: @escaping (Error?) -> Void) {
        guard let manager else {
            completion(POSIXError(.ENOTCONN))
            return
        }
        let answer: SMB2Manager.SimpleCompletionHandler = { error in
            DispatchQueue.main.async { completion(error) }
        }
        if isFolder {
            manager.removeDirectory(atPath: path, recursive: true, completionHandler: answer)
        } else {
            manager.removeFile(atPath: path, completionHandler: answer)
        }
    }

    func disconnect() {
        manager?.disconnectShare(gracefully: false, completionHandler: nil)
        manager = nil
    }

    private static func item(_ entry: [URLResourceKey: any Sendable]) -> ShareItem? {
        guard let name = entry[.nameKey] as? String, !name.isEmpty else { return nil }
        return ShareItem(
            name: name, isFolder: (entry[.isDirectoryKey] as? NSNumber)?.boolValue ?? false,
            size: (entry[.fileSizeKey] as? NSNumber)?.int64Value ?? 0,
            modified: entry[.contentModificationDateKey] as? Date)
    }
}

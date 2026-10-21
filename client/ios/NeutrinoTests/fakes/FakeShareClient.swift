import Foundation

@testable import Neutrino

/// A share in memory that answers as AMSMB2 does: a name the folder holds fails with `EEXIST`, a path it lacks
/// with `ENOENT`, and a cancelled transfer ends with no failure. With `isHolding` a transfer reports half its
/// bytes and waits for `finish`.
final class FakeShareClient: ShareClient {
    /// The share's files by path.
    var files: [String: Data] = [:]

    /// The share's folders by path.
    var folders: Set<String> = []

    /// What the next connects fail with; nil logs in.
    var connectFailure: Error?

    /// Whether transfers wait for `finish`.
    var isHolding = false

    /// The port, share and login of the last connect.
    private(set) var connected: (port: Int, share: String, login: ShareLogin)?

    /// How many connects there were.
    private(set) var connects = 0

    /// Whether the connection was closed.
    private(set) var isDisconnected = false

    /// Every path removed, in order.
    private(set) var removed: [String] = []

    /// What connect does besides answering, such as dialling the forward.
    var onConnect: ((Int) -> Void)?

    private var held: [(Error?) -> Void] = []

    func connect(port: Int, share: String, login: ShareLogin, completion: @escaping (Error?) -> Void) {
        connected = (port, share, login)
        connects += 1
        isDisconnected = false
        onConnect?(port)
        completion(connectFailure)
    }

    func list(_ path: String, completion: @escaping (Result<[ShareItem], Error>) -> Void) {
        guard path.isEmpty || folders.contains(path) else {
            completion(.failure(POSIXError(.ENOENT)))
            return
        }
        let folderItems = folders.filter { parent(of: $0) == path }.map {
            ShareItem(name: name(of: $0), isFolder: true, size: 0, modified: nil)
        }
        let fileItems = files.filter { parent(of: $0.key) == path }.map {
            ShareItem(name: name(of: $0.key), isFolder: false, size: Int64($0.value.count), modified: nil)
        }
        completion(.success(Array(folderItems) + Array(fileItems)))
    }

    func download(
        _ path: String, to url: URL, cancel: ShareCancel, progress: @escaping (Int64, Int64) -> Void,
        completion: @escaping (Error?) -> Void
    ) {
        guard let data = files[path] else {
            completion(POSIXError(.ENOENT))
            return
        }
        let total = Int64(data.count)
        let write: (Error?) -> Void = { error in
            if error == nil, !cancel.isCancelled { try? data.write(to: url) }
            completion(error)
        }
        if isHolding {
            progress(total / 2, total)
            held.append(write)
        } else {
            progress(total, total)
            write(nil)
        }
    }

    func upload(
        _ url: URL, to path: String, cancel: ShareCancel, progress: @escaping (Int64) -> Void,
        completion: @escaping (Error?) -> Void
    ) {
        guard files[path] == nil, !folders.contains(path) else {
            completion(POSIXError(.EEXIST))
            return
        }
        let data = (try? Data(contentsOf: url)) ?? Data()
        files[path] = Data()
        let write: (Error?) -> Void = { [weak self] error in
            if error == nil, !cancel.isCancelled { self?.files[path] = data }
            completion(error)
        }
        if isHolding {
            progress(Int64(data.count / 2))
            held.append(write)
        } else {
            progress(Int64(data.count))
            write(nil)
        }
    }

    func makeFolder(_ path: String, completion: @escaping (Error?) -> Void) {
        guard files[path] == nil, !folders.contains(path) else {
            completion(POSIXError(.EEXIST))
            return
        }
        folders.insert(path)
        completion(nil)
    }

    func move(_ path: String, to target: String, completion: @escaping (Error?) -> Void) {
        guard files[target] == nil, !folders.contains(target) else {
            completion(POSIXError(.EEXIST))
            return
        }
        if let data = files.removeValue(forKey: path) {
            files[target] = data
        } else if folders.remove(path) != nil {
            folders.insert(target)
        } else {
            completion(POSIXError(.ENOENT))
            return
        }
        completion(nil)
    }

    func remove(_ path: String, isFolder: Bool, completion: @escaping (Error?) -> Void) {
        removed.append(path)
        if isFolder {
            folders = folders.filter { $0 != path && !$0.hasPrefix(path + "/") }
            files = files.filter { !$0.key.hasPrefix(path + "/") }
        } else {
            files[path] = nil
        }
        completion(nil)
    }

    func disconnect() {
        isDisconnected = true
    }

    /// End every transfer that waits, each with one failure or none.
    ///
    /// - Parameter error: What they fail with; nil ends them.
    func finish(_ error: Error? = nil) {
        let waiting = held
        held = []
        for end in waiting { end(error) }
    }

    private func parent(of path: String) -> String {
        guard let slash = path.lastIndex(of: "/") else { return "" }
        return String(path[..<slash])
    }

    private func name(of path: String) -> String {
        guard let slash = path.lastIndex(of: "/") else { return path }
        return String(path[path.index(after: slash)...])
    }
}

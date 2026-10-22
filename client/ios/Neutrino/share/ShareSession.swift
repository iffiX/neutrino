import Foundation

/// One open share: its forward, its SMB connection, the folder the page shows, and every transfer and job on the
/// page. The forward listens on `127.0.0.1` at a port the system picks, each accepted connection one `connect`
/// stream naming the file entry, and accepts nothing while the hub has no channel. Every call runs on the main
/// queue.
final class ShareSession {
    /// The share.
    let target: ShareTarget

    private let login: ShareLogin
    private let makeClient: () -> ShareClient
    private let openConnect: () -> Result<ChannelStream, ClientError>
    private let directory: URL
    private var client: ShareClient?
    private var relay: ForwardRelay?
    private var hubRefusal: ClientError?
    private var isChannelOpen = true
    private var generation = 0
    private var listing = 0
    private var cancels: [String: ShareCancel] = [:]

    /// Called after every change of the page.
    var onChange: (() -> Void)?

    /// The page as it draws.
    private(set) var view: ShareView {
        didSet {
            if view != oldValue { onChange?() }
        }
    }

    /// Prepare a share.
    ///
    /// - Parameters:
    ///   - target: The share.
    ///   - login: The account it is opened with.
    ///   - makeClient: Makes the SMB client of one connection.
    ///   - openConnect: Opens one `connect` stream naming the share's entry.
    ///   - directory: The app's temporary directory for shares; this share's files go in a directory of its own
    ///     under it.
    init(
        target: ShareTarget, login: ShareLogin, makeClient: @escaping () -> ShareClient,
        openConnect: @escaping () -> Result<ChannelStream, ClientError>, directory: URL
    ) {
        self.target = target
        self.login = login
        self.makeClient = makeClient
        self.openConnect = openConnect
        self.directory = directory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        view = ShareView(target: target)
    }

    /// Make the forward, connect through it and log in.
    ///
    /// - Parameter completion: Called with nil once logged in, or with the refusal, the connection then closed.
    func start(_ completion: @escaping (ClientError?) -> Void) {
        stopConnection()
        generation += 1
        let mine = generation
        hubRefusal = nil
        let relay = ForwardRelay(name: target.id) { [weak self] in
            self?.openConnect()
                ?? .failure(.refusal(Channel.codeHubUnreachable, ["detail": "the share page closed"]))
        }
        relay.onRefused = { [weak self] refusal in self?.hubRefusal = refusal }
        relay.channelChanged(isOpen: isChannelOpen)
        let port: Int
        do {
            port = try relay.start(port: 0)
        } catch {
            completion(refusal(error))
            return
        }
        self.relay = relay
        let client = makeClient()
        self.client = client
        ClientLog.info("forwarding \(Forward.bindHost):\(port) to the share \(target.id) through the hub")
        client.connect(port: port, share: target.share, login: login) { [weak self] error in
            guard let self, self.generation == mine else { return }
            guard let error else {
                self.view.isConnected = true
                completion(nil)
                return
            }
            let refusal = self.refusal(error)
            self.stopConnection()
            completion(refusal)
        }
    }

    /// Close the share: its connection, its forward and its files.
    func close() {
        generation += 1
        for cancel in cancels.values { cancel.cancel() }
        cancels = [:]
        stopConnection()
        try? FileManager.default.removeItem(at: directory)
    }

    /// The time in the background is ending: every transfer that runs is cut and shows `share_interrupted`, and
    /// the connection and the forward close.
    func suspend() {
        generation += 1
        for (key, transfer) in view.transfers where transfer.isRunning {
            view.transfers[key]?.error = .refusal(SharePage.codeInterrupted)
        }
        cancels = [:]
        view.jobs = [:]
        view.isListing = false
        view.isMakingFolder = false
        stopConnection()
    }

    /// The app came back to the foreground: the forward listens again, the share is logged in to again and the
    /// folder read again.
    ///
    /// - Parameter completion: Called with nil once logged in, or with the refusal, which the page line shows.
    func resume(_ completion: @escaping (ClientError?) -> Void) {
        start { [weak self] refusal in
            guard let self else { return }
            if let refusal {
                self.view.isListing = false
                self.view.error = refusal
            } else {
                self.view.error = nil
                self.reload()
            }
            completion(refusal)
        }
    }

    /// The hub's channel opened or closed: the forward accepts nothing while it is closed.
    ///
    /// - Parameter isOpen: Whether the hub has a channel now.
    func channelChanged(isOpen: Bool) {
        isChannelOpen = isOpen
        relay?.channelChanged(isOpen: isOpen)
    }

    /// Read the folder shown again.
    func reload() {
        list(view.path)
    }

    /// A pull on the list or a refresh: every code on the page goes and the folder is read again, after logging in
    /// again when the share's connection ended.
    ///
    /// - Parameter completion: Called with nil once the folder is being read, or with the login's refusal.
    func refresh(_ completion: @escaping (ClientError?) -> Void) {
        view.error = nil
        view.errors = [:]
        guard relay?.isCarrying != true else {
            reload()
            completion(nil)
            return
        }
        view.isListing = true
        resume(completion)
    }

    /// Open a folder of the folder shown.
    ///
    /// - Parameter item: The folder.
    func enter(_ item: ShareItem) {
        guard item.isFolder else { return }
        view.path = view.path.child(item.name)
        view.items = []
        view.error = nil
        reload()
    }

    /// Go up one folder.
    ///
    /// - Returns: False at the share's root, where the page closes instead.
    func back() -> Bool {
        guard let parent = view.path.parent else { return false }
        view.path = parent
        view.items = []
        view.error = nil
        reload()
        return true
    }

    /// A tap on a file: it is read into the temporary directory, then the preview shows it.
    ///
    /// - Parameter item: The file.
    func open(_ item: ShareItem) {
        read(view.path.child(item.name), kind: .open, total: item.size)
    }

    /// Save to Files on a file: it is read into the temporary directory, then the export picker saves it.
    ///
    /// - Parameter item: The file.
    func save(_ item: ShareItem) {
        read(view.path.child(item.name), kind: .save, total: item.size)
    }

    /// Upload from Files: each picked file is copied into the temporary directory, then written into the folder
    /// shown under the first free name.
    ///
    /// - Parameter urls: The picked files.
    func upload(_ urls: [URL]) {
        for url in urls {
            let folder = view.path
            let name = url.lastPathComponent
            let key = folder.child(name).text
            guard view.transfers[key] == nil else {
                ClientLog.info("an upload of \(key) runs; the pick is dropped")
                continue
            }
            let cancel = ShareCancel()
            cancels[key] = cancel
            view.transfers[key] = ShareTransfer(kind: .upload, path: folder.child(name), askedName: name)
            let place = directory.appendingPathComponent(UUID().uuidString, isDirectory: true)
            let mine = generation
            DispatchQueue.global(qos: .userInitiated).async {
                let copied = Result { try Self.copy(url, into: place) }
                DispatchQueue.main.async { [weak self] in
                    self?.copied(copied, key: key, cancel: cancel, generation: mine)
                }
            }
        }
    }

    /// Upload from Photos: each picked item puts its file into a folder of the share's own, and the file is then
    /// written into the folder shown as a file Upload from Files picked is. An item not handed over writes
    /// `share_photo_unavailable` on the page's error line, and the other items upload.
    ///
    /// - Parameter deliveries: The picked items.
    func upload(deliveries: [ShareDelivery]) {
        let folder = view.path
        let mine = generation
        for delivery in deliveries {
            let place = directory.appendingPathComponent(UUID().uuidString, isDirectory: true)
            do {
                try FileManager.default.createDirectory(at: place, withIntermediateDirectories: true)
            } catch {
                view.error = .refusal(Channel.codeClientInternal, ["error": "\(error)"])
                continue
            }
            delivery.deliver(into: place) { result in
                DispatchQueue.main.async { [weak self] in
                    self?.delivered(result, into: folder, generation: mine)
                }
            }
        }
    }

    /// Cancel on a transfer's row: a running transfer stops, and one that ended in a code goes.
    ///
    /// - Parameter key: The transfer's path in the share.
    func cancel(_ key: String) {
        guard let transfer = view.transfers.removeValue(forKey: key) else { return }
        if let cancel = cancels.removeValue(forKey: key) { cancel.cancel() }
        if !transfer.isRunning, let source = transfer.source {
            try? FileManager.default.removeItem(at: source.deletingLastPathComponent())
        }
    }

    /// Retry on a transfer that ended in a code: a read runs again; a write whose cut left a part deletes it
    /// and writes the same name again, and any other write starts again from the name asked for.
    ///
    /// - Parameter key: The transfer's path in the share.
    func retry(_ key: String) {
        guard let transfer = view.transfers[key], !transfer.isRunning, let client else { return }
        switch transfer.kind {
        case .open, .save:
            view.transfers[key] = nil
            read(transfer.path, kind: transfer.kind, total: transfer.total)
        case .upload:
            guard transfer.source != nil else {
                view.transfers[key] = nil
                return
            }
            let cancel = ShareCancel()
            cancels[key] = cancel
            view.transfers[key]?.error = nil
            guard transfer.done > 0 else {
                write(transfer, from: key, name: transfer.askedName, attempt: 0, isNumbered: true, cancel: cancel)
                return
            }
            let mine = generation
            client.remove(key, isFolder: false) { [weak self] _ in
                guard let self, self.generation == mine, self.cancels[key] === cancel else { return }
                self.write(transfer, from: key, name: transfer.path.name, attempt: 0, isNumbered: false, cancel: cancel)
            }
        }
    }

    /// Rename a file or a folder of the folder shown.
    ///
    /// - Parameters:
    ///   - item: The file or folder.
    ///   - name: Its new name.
    func rename(_ item: ShareItem, to name: String) {
        let path = view.path.child(item.name)
        guard ShareName.isValid(name), name != item.name, let client, begin(path.text, .renaming) else { return }
        let mine = generation
        client.move(path.text, to: view.path.child(name).text) { [weak self] error in
            self?.ended(path.text, error, generation: mine)
        }
    }

    /// Delete a file, or a folder with everything in it.
    ///
    /// - Parameter item: The file or folder.
    func delete(_ item: ShareItem) {
        let path = view.path.child(item.name)
        guard let client, begin(path.text, .deleting) else { return }
        let mine = generation
        client.remove(path.text, isFolder: item.isFolder) { [weak self] error in
            self?.ended(path.text, error, generation: mine)
        }
    }

    /// New folder in the folder shown, under the first free name.
    ///
    /// - Parameter name: The name asked for.
    func makeFolder(_ name: String) {
        guard ShareName.isValid(name), !view.isMakingFolder, client != nil else { return }
        view.isMakingFolder = true
        view.error = nil
        makeFolder(name, in: view.path, attempt: 0)
    }

    /// The preview closed: its file goes.
    func closePreview() {
        guard let preview = view.preview else { return }
        view.preview = nil
        try? FileManager.default.removeItem(at: preview.deletingLastPathComponent())
    }

    /// The export picker closed: its file goes.
    func closeExport() {
        guard let export = view.export else { return }
        view.export = nil
        try? FileManager.default.removeItem(at: export.deletingLastPathComponent())
    }

    private func list(_ path: SharePath) {
        guard let client else { return }
        listing += 1
        let mine = listing
        let connection = generation
        view.isListing = true
        client.list(path.text) { [weak self] result in
            guard let self, self.generation == connection, self.listing == mine else { return }
            self.view.isListing = false
            switch result {
            case .success(let items): self.view.items = ShareItem.ordered(items)
            case .failure(let error): self.view.error = self.refusal(error)
            }
        }
    }

    private func read(_ path: SharePath, kind: ShareTransferKind, total: Int64) {
        let key = path.text
        guard let client, view.transfers[key]?.isRunning != true, view.jobs[key] == nil else {
            ClientLog.info("a job runs on \(key); the press is dropped")
            return
        }
        view.errors[key] = nil
        let place = directory.appendingPathComponent(UUID().uuidString, isDirectory: true)
        let local = place.appendingPathComponent(path.name)
        do {
            try FileManager.default.createDirectory(at: place, withIntermediateDirectories: true)
        } catch {
            view.errors[key] = .refusal(Channel.codeClientInternal, ["error": "\(error)"])
            return
        }
        let cancel = ShareCancel()
        cancels[key] = cancel
        view.transfers[key] = ShareTransfer(kind: kind, path: path, askedName: path.name, total: total)
        let mine = generation
        client.download(
            key, to: local, cancel: cancel,
            progress: { [weak self] done, size in self?.progressed(key, cancel, done: done, total: size) },
            completion: { [weak self] error in
                guard let self, self.generation == mine, self.cancels[key] === cancel, !cancel.isCancelled else {
                    try? FileManager.default.removeItem(at: place)
                    return
                }
                self.cancels[key] = nil
                if let error {
                    try? FileManager.default.removeItem(at: place)
                    self.view.transfers[key]?.error = self.refusal(error)
                    return
                }
                self.view.transfers[key] = nil
                switch kind {
                case .open: self.view.preview = local
                case .save: self.view.export = local
                case .upload: break
                }
            })
    }

    private func delivered(_ delivered: Result<URL, Error>, into folder: SharePath, generation mine: Int) {
        let file: URL
        switch delivered {
        case .failure(let error):
            ClientLog.info("an item from Photos for \(target.id) was not handed over: \(error)")
            view.error = .refusal(SharePage.codePhotoUnavailable)
            return
        case .success(let url):
            file = url
        }
        let name = file.lastPathComponent
        let key = folder.child(name).text
        guard view.transfers[key] == nil else {
            ClientLog.info("an upload of \(key) runs; the item from Photos is dropped")
            try? FileManager.default.removeItem(at: file.deletingLastPathComponent())
            return
        }
        let cancel = ShareCancel()
        var transfer = ShareTransfer(kind: .upload, path: folder.child(name), askedName: name)
        if generation == mine {
            cancels[key] = cancel
        } else {
            transfer.error = .refusal(SharePage.codeInterrupted)
        }
        view.transfers[key] = transfer
        let attributes = try? FileManager.default.attributesOfItem(atPath: file.path)
        copied(
            .success((file, (attributes?[.size] as? NSNumber)?.int64Value ?? 0)), key: key, cancel: cancel,
            generation: mine)
    }

    private func copied(
        _ copied: Result<(URL, Int64), Error>, key: String, cancel: ShareCancel, generation mine: Int
    ) {
        let isCurrent = cancels[key] === cancel
        switch copied {
        case .failure(let error):
            guard isCurrent else { return }
            cancels[key] = nil
            view.transfers[key]?.error = .refusal(Channel.codeClientInternal, ["error": "\(error)"])
        case .success(let (source, size)):
            guard view.transfers[key] != nil, isCurrent || generation != mine, !cancel.isCancelled else {
                try? FileManager.default.removeItem(at: source.deletingLastPathComponent())
                return
            }
            view.transfers[key]?.source = source
            view.transfers[key]?.total = size
            guard generation == mine, let transfer = view.transfers[key] else { return }
            write(transfer, from: key, name: transfer.askedName, attempt: 0, isNumbered: true, cancel: cancel)
        }
    }

    private func write(
        _ transfer: ShareTransfer, from previous: String, name: String, attempt: Int, isNumbered: Bool,
        cancel: ShareCancel
    ) {
        view.transfers[previous] = nil
        cancels[previous] = nil
        guard let client, let source = transfer.source else { return }
        let folder = transfer.path.parent ?? SharePath()
        let target = folder.child(ShareName.numbered(name, isFolder: false, attempt: attempt))
        let key = target.text
        let next = ShareTransfer(
            kind: .upload, path: target, askedName: transfer.askedName, source: source, total: transfer.total)
        cancels[key] = cancel
        view.transfers[key] = next
        let mine = generation
        var written: Int64 = 0
        client.upload(
            source, to: key, cancel: cancel,
            progress: { [weak self] done in
                written = done
                self?.progressed(key, cancel, done: done, total: 0)
            },
            completion: { [weak self] error in
                guard let self else { return }
                if cancel.isCancelled {
                    try? FileManager.default.removeItem(at: source.deletingLastPathComponent())
                    if self.generation == mine, error == nil || written > 0 {
                        self.client?.remove(key, isFolder: false) { _ in }
                    }
                    return
                }
                guard self.generation == mine, self.cancels[key] === cancel else { return }
                guard let error else {
                    self.cancels[key] = nil
                    self.view.transfers[key] = nil
                    try? FileManager.default.removeItem(at: source.deletingLastPathComponent())
                    if folder == self.view.path { self.reload() }
                    return
                }
                if isNumbered, (error as? POSIXError)?.code == .EEXIST, attempt + 1 < SharePage.nameAttempts {
                    self.write(next, from: key, name: name, attempt: attempt + 1, isNumbered: true, cancel: cancel)
                    return
                }
                self.cancels[key] = nil
                self.view.transfers[key]?.error = self.refusal(error)
            })
    }

    private func makeFolder(_ name: String, in folder: SharePath, attempt: Int) {
        guard let client else { return }
        let mine = generation
        let path = folder.child(ShareName.numbered(name, isFolder: true, attempt: attempt))
        client.makeFolder(path.text) { [weak self] error in
            guard let self, self.generation == mine else { return }
            if let error, (error as? POSIXError)?.code == .EEXIST, attempt + 1 < SharePage.nameAttempts {
                self.makeFolder(name, in: folder, attempt: attempt + 1)
                return
            }
            self.view.isMakingFolder = false
            if let error {
                self.view.error = self.refusal(error)
            } else if folder == self.view.path {
                self.reload()
            }
        }
    }

    private func begin(_ key: String, _ job: ShareItemJob) -> Bool {
        guard view.jobs[key] == nil, view.transfers[key]?.isRunning != true else {
            ClientLog.info("a job runs on \(key); the press is dropped")
            return false
        }
        view.jobs[key] = job
        view.errors[key] = nil
        view.transfers[key] = nil
        return true
    }

    private func ended(_ key: String, _ error: Error?, generation mine: Int) {
        guard generation == mine else { return }
        view.jobs[key] = nil
        if let error {
            view.errors[key] = refusal(error)
        } else {
            reload()
        }
    }

    private func progressed(_ key: String, _ cancel: ShareCancel, done: Int64, total: Int64) {
        guard cancels[key] === cancel else { return }
        view.transfers[key]?.done = done
        if total > 0 { view.transfers[key]?.total = total }
    }

    private func refusal(_ error: Error) -> ClientError {
        let refusal = ShareRefusal.of(error, hubRefusal: hubRefusal, isCarried: relay?.isCarrying ?? false)
        ClientLog.info("the share \(target.id) failed with \(refusal.code): \(error)")
        return refusal
    }

    private func stopConnection() {
        view.isConnected = false
        relay?.close()
        relay = nil
        client?.disconnect()
        client = nil
    }

    private static func copy(_ url: URL, into place: URL) throws -> (URL, Int64) {
        let isScoped = url.startAccessingSecurityScopedResource()
        defer {
            if isScoped { url.stopAccessingSecurityScopedResource() }
        }
        try FileManager.default.createDirectory(at: place, withIntermediateDirectories: true)
        let copy = place.appendingPathComponent(url.lastPathComponent)
        try FileManager.default.copyItem(at: url, to: copy)
        let size = try FileManager.default.attributesOfItem(atPath: copy.path)[.size] as? NSNumber
        return (copy, size?.int64Value ?? 0)
    }
}

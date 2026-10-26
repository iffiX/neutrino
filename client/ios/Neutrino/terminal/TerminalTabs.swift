import Foundation

/// Every terminal tab of the app, outliving the page that draws them: the tabs follow the session lists of the
/// connected hubs, and each tab keeps its shell stream and its last output so a new view can draw it again. A
/// new shell is opened with a session id this phone makes, as the account picked on its machine; a listed one is
/// attached with `is_resumed`, its kept output first. What the person types goes to the tab's stream in the order
/// typed, a later size as a `resize` record, and `persist` and `stop_session` are frames naming only the session.
/// Every call runs on the main queue.
final class TerminalTabs {
    private let hubOf: (String) -> TerminalHub?
    private let clock: ClientClock
    private var streams: [String: TransportStream] = [:]
    private var outputs: [String: Data] = [:]
    private var sizes: [String: (cols: Int, rows: Int)] = [:]
    private var dismissed: Set<String> = []
    private var drops: [String: TerminalDrop] = [:]
    private var replaying: Set<String> = []

    /// Called after every change of the tabs, the shown tab, the picked machine or the tabs that clear.
    var onChange: (() -> Void)?

    /// Called with a tab and the bytes its shell wrote, as they arrive.
    var onOutput: ((String, Data) -> Void)?

    /// Called with a tab whose shell attached again, as the first bytes of its kept output arrive: the output
    /// comes again, drawn from a clear screen. A tab whose session is gone keeps its last output.
    var onReplay: ((String) -> Void)?

    /// Every tab, in the order made.
    private(set) var tabs: [TerminalTab] = [] {
        didSet {
            if tabs != oldValue { onChange?() }
        }
    }

    /// The tab shown, empty for none.
    private(set) var active = "" {
        didSet {
            if active != oldValue { onChange?() }
        }
    }

    /// The machine a new terminal opens on, as binding id and device id, or nil for none picked.
    private(set) var picked: TerminalMachine? {
        didSet {
            if picked != oldValue { onChange?() }
        }
    }

    /// The account a new terminal runs as on the picked machine, empty for its first enabled one.
    private(set) var pickedAccount = "" {
        didSet {
            if pickedAccount != oldValue { onChange?() }
        }
    }

    /// The tabs whose Clear is still dropping what arrives.
    private(set) var clearing: Set<String> = [] {
        didSet {
            if clearing != oldValue { onChange?() }
        }
    }

    /// Prepare the tabs.
    ///
    /// - Parameters:
    ///   - hubOf: One hub's terminal questions, by binding id, or nil while it is not connected.
    ///   - clock: The time Clear's dropping is measured by.
    init(hubOf: @escaping (String) -> TerminalHub?, clock: ClientClock) {
        self.hubOf = hubOf
        self.clock = clock
    }

    /// What a tab's shell wrote so far, kept to draw it again in a new view.
    ///
    /// - Parameter sessionId: The tab.
    /// - Returns: At most the last 256 KiB.
    func keptOutput(_ sessionId: String) -> Data {
        outputs[sessionId] ?? Data()
    }

    /// Take one round of the hubs' session lists.
    ///
    /// - Parameter hubs: Every hub's view.
    func take(_ hubs: [HubView]) {
        let (listings, listedHubs) = TerminalSessionMerge.listed(hubs)
        let listedIds = Set(listings.map(\.session.sessionId))
        dismissed = dismissed.intersection(listedIds)
        tabs = TerminalSessionMerge.merge(tabs, listings: listings, listedHubs: listedHubs, dismissed: dismissed)
        if !tabs.contains(where: { $0.sessionId == active }) { active = tabs.first?.sessionId ?? "" }
    }

    /// Pick the machine a new terminal opens on.
    ///
    /// - Parameter machine: The machine.
    func pick(_ machine: TerminalMachine) {
        if picked != machine { pickedAccount = "" }
        picked = machine
    }

    /// Pick the account a new terminal runs as on the picked machine.
    ///
    /// - Parameter account: One of the machine's enabled accounts.
    func pickAccount(_ account: String) {
        pickedAccount = account
    }

    /// Show one tab; its stream attaches at the first size its view reports.
    ///
    /// - Parameter sessionId: The tab.
    func select(_ sessionId: String) {
        if tab(sessionId) != nil { active = sessionId }
    }

    /// Make a tab for a new shell and show it; its shell opens at the first size the view reports.
    ///
    /// - Parameters:
    ///   - bindingId: The hub.
    ///   - deviceId: The machine.
    ///   - name: The machine's name.
    ///   - account: The account the shell runs as, empty for the machine's first enabled one.
    /// - Returns: The tab's session id.
    @discardableResult
    func create(bindingId: String, deviceId: String, name: String, account: String = "") -> String {
        let sessionId = UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()
        tabs.append(
            TerminalTab(
                sessionId: sessionId, bindingId: bindingId, deviceId: deviceId, name: name, account: account,
                phase: .connecting))
        active = sessionId
        return sessionId
    }

    /// Take a view's size: the first opens or attaches the shell, a later one resizes it.
    ///
    /// - Parameters:
    ///   - sessionId: The tab.
    ///   - cols: The width in columns.
    ///   - rows: The height in rows.
    func sized(_ sessionId: String, cols: Int, rows: Int) {
        guard let tab = tab(sessionId), cols > 0, rows > 0 else { return }
        sizes[sessionId] = (cols, rows)
        if let stream = streams[sessionId], !stream.isDone {
            let size: [String: JSONValue] = ["cols": .int(cols), "rows": .int(rows)]
            stream.sendRecord(type: Transport.recordResize, payload: Data(size.jsonText.utf8))
        } else if tab.phase != .ended && tab.phase != .open {
            attach(tab, cols: cols, rows: rows)
        }
    }

    /// Attach a detached tab's shell again at its last size, as once its hub answers again.
    ///
    /// - Parameter sessionId: The tab.
    func reattach(_ sessionId: String) {
        guard let tab = tab(sessionId), tab.phase == .detached, let size = sizes[sessionId] else { return }
        attach(tab, cols: size.cols, rows: size.rows)
    }

    /// Send what the person typed, after everything typed before it.
    ///
    /// - Parameters:
    ///   - sessionId: The tab.
    ///   - bytes: The bytes.
    func input(_ sessionId: String, _ bytes: Data) {
        streams[sessionId]?.send(bytes)
    }

    /// Clear a tab: Ctrl+C goes to the shell after what was typed before it, the kept output is dropped, and so
    /// is what arrives until the stream has been quiet for half a second, for twenty seconds at most, or until
    /// the shell ends. A tab with no open shell takes no Clear.
    ///
    /// - Parameter sessionId: The tab.
    /// - Returns: Whether the Clear was taken.
    @discardableResult
    func clear(_ sessionId: String) -> Bool {
        guard streams[sessionId] != nil else { return false }
        outputs[sessionId] = nil
        let now = clock.now
        let drop = TerminalDrop(since: now, last: now)
        drops[sessionId] = drop
        clearing.insert(sessionId)
        input(sessionId, Data([TerminalPage.controlC]))
        scheduleDropEnd(sessionId, drop)
        return true
    }

    /// Set whether a tab's session outlives every window and whether others list it; the tab shows the new
    /// values at once, and the next state frame confirms them.
    ///
    /// - Parameters:
    ///   - sessionId: The tab.
    ///   - isPersistent: Whether the session outlives every window.
    ///   - isShared: Whether every client with terminal rights on the machine lists it.
    func persist(_ sessionId: String, isPersistent: Bool, isShared: Bool) {
        guard let tab = tab(sessionId), tab.canPersist else { return }
        change(sessionId) { tab in
            tab.isPersistent = isPersistent
            tab.isShared = isShared
            tab.note = nil
        }
        hubOf(tab.bindingId)?.persist(sessionId: sessionId, isPersistent: isPersistent, isShared: isShared) {
            [weak self] result in
            if case .failure(let refusal) = result { self?.change(sessionId) { $0.note = refusal } }
        }
    }

    /// Close a tab: an ended tab goes, a persistent or shared session is ended on its machine with `stop_session`
    /// and its tab goes once the machine agrees, and any other closes with its stream.
    ///
    /// - Parameter sessionId: The tab.
    func close(_ sessionId: String) {
        guard let tab = tab(sessionId) else { return }
        if tab.phase != .ended && tab.isKept {
            stopSession(tab)
        } else {
            remove(sessionId)
        }
    }

    /// A hub is being left: its tabs go.
    ///
    /// - Parameter bindingId: The hub.
    func forget(bindingId: String) {
        for tab in tabs where tab.bindingId == bindingId { remove(tab.sessionId) }
    }

    private func stopSession(_ tab: TerminalTab) {
        guard let hub = hubOf(tab.bindingId) else {
            change(tab.sessionId) { $0.note = .refusal(Channel.codeHubUnreachable) }
            return
        }
        hub.stopSession(tab.sessionId) { [weak self] result in
            switch result {
            case .failure(let refusal): self?.change(tab.sessionId) { $0.note = refusal }
            case .success: self?.remove(tab.sessionId)
            }
        }
    }

    private func remove(_ sessionId: String) {
        dismissed.insert(sessionId)
        if let stream = streams.removeValue(forKey: sessionId) {
            stream.onBytes = nil
            stream.onEnd = nil
            stream.close()
        }
        outputs[sessionId] = nil
        replaying.remove(sessionId)
        stopDropping(sessionId)
        let before = tabs.firstIndex { $0.sessionId == sessionId } ?? 0
        tabs.removeAll { $0.sessionId == sessionId }
        if active == sessionId {
            active = tabs.isEmpty ? "" : tabs[min(before, tabs.count - 1)].sessionId
        }
    }

    private func attach(_ tab: TerminalTab, cols: Int, rows: Int) {
        guard let hub = hubOf(tab.bindingId) else {
            change(tab.sessionId) { tab in
                tab.phase = .detached
                tab.note = .refusal(Channel.codeHubUnreachable)
            }
            return
        }
        let isResumed = tab.phase == .detached
        let open: [String: JSONValue] = [
            "kind": .string(Channel.kindShell),
            "device_id": .string(tab.deviceId),
            "cols": .int(cols),
            "rows": .int(rows),
            "account": .string(tab.account),
            "session_id": .string(tab.sessionId),
            "is_resumed": .bool(isResumed),
            "is_shared": .bool(tab.isShared),
        ]
        change(tab.sessionId) { $0.phase = .connecting }
        switch hub.openShell(open) {
        case .failure(let refusal):
            change(tab.sessionId) { tab in
                tab.phase = .detached
                tab.note = refusal
            }
        case .success(let stream):
            if isResumed { replaying.insert(tab.sessionId) }
            streams[tab.sessionId] = stream
            change(tab.sessionId) { tab in
                tab.phase = .open
                tab.note = nil
            }
            stream.onBytes = { [weak self] data in self?.take(data, for: tab.sessionId) }
            stream.onEnd = { [weak self, weak stream] refusal in
                guard let self, let stream else { return }
                self.ended(tab.sessionId, stream: stream, refusal: refusal)
            }
        }
    }

    private func take(_ data: Data, for sessionId: String) {
        if replaying.remove(sessionId) != nil {
            outputs[sessionId] = nil
            onReplay?(sessionId)
        }
        if isDropped(sessionId) { return }
        var kept = (outputs[sessionId] ?? Data()) + data
        if kept.count > TerminalPage.keptBytes { kept = kept.suffix(TerminalPage.keptBytes) }
        outputs[sessionId] = Data(kept)
        onOutput?(sessionId, data)
    }

    private func ended(_ sessionId: String, stream: TransportStream, refusal: ClientError?) {
        if streams[sessionId] === stream { streams[sessionId] = nil }
        replaying.remove(sessionId)
        if drops[sessionId] != nil { stopDropping(sessionId) }
        change(sessionId) { tab in
            if let refusal, refusal.code == "session_unknown" {
                tab.phase = .ended
                tab.note = refusal
                tab.isPersistent = false
                tab.isShared = false
            } else if let refusal {
                tab.phase = .detached
                tab.note = refusal
            } else {
                tab.phase = tab.isKept ? .detached : .ended
                tab.note = nil
            }
        }
    }

    private func isDropped(_ sessionId: String) -> Bool {
        guard let drop = drops[sessionId] else { return false }
        let now = clock.now
        if now < drop.endsAt {
            drop.last = now
            return true
        }
        stopDropping(sessionId)
        return false
    }

    private func scheduleDropEnd(_ sessionId: String, _ drop: TerminalDrop) {
        clock.schedule(after: max(drop.endsAt - clock.now, 0)) { [weak self] in
            guard let self, self.drops[sessionId] === drop else { return }
            if self.clock.now >= drop.endsAt {
                self.stopDropping(sessionId)
            } else {
                self.scheduleDropEnd(sessionId, drop)
            }
        }
    }

    private func stopDropping(_ sessionId: String) {
        drops[sessionId] = nil
        clearing.remove(sessionId)
    }

    private func tab(_ sessionId: String) -> TerminalTab? {
        tabs.first { $0.sessionId == sessionId }
    }

    private func change(_ sessionId: String, _ transform: (inout TerminalTab) -> Void) {
        tabs = tabs.map { tab in
            guard tab.sessionId == sessionId else { return tab }
            var next = tab
            transform(&next)
            return next
        }
    }
}

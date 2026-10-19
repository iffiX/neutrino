import Foundation

/// Every terminal tab of the app, outliving the page that draws them: the tabs follow the session lists of the
/// connected hubs, and each tab keeps its shell stream and its last output so a new view can draw it again. A
/// new shell is opened with a session id this phone makes; a listed one is attached with `is_resumed`, its kept
/// output first. What the person types goes to the tab's stream in the order typed. Every call runs on the main
/// queue.
final class TerminalTabs {
    private let open: (String, String, [String: JSONValue], Bool) -> Result<ChannelStream, ClientError>
    private let clock: ClientClock
    private var streams: [String: ChannelStream] = [:]
    private var outputs: [String: Data] = [:]
    private var sizes: [String: (cols: Int, rows: Int)] = [:]
    private var dismissed: Set<String> = []
    private var drops: [String: TerminalDrop] = [:]

    /// Called after every change of the tabs, the shown tab, the picked machine or the tabs that clear.
    var onChange: (() -> Void)?

    /// Called with a tab and the bytes its shell wrote, as they arrive.
    var onOutput: ((String, Data) -> Void)?

    /// Called with a tab whose shell attaches again: its kept output comes again, drawn from a clear screen.
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

    /// The tabs whose Clear is still dropping what arrives.
    private(set) var clearing: Set<String> = [] {
        didSet {
            if clearing != oldValue { onChange?() }
        }
    }

    /// Prepare the tabs.
    ///
    /// - Parameters:
    ///   - open: Opens a stream on a hub's live socket: the binding, the kind, the arguments, whether it carries
    ///     bytes.
    ///   - clock: The time Clear's dropping is measured by.
    init(
        open: @escaping (String, String, [String: JSONValue], Bool) -> Result<ChannelStream, ClientError>,
        clock: ClientClock
    ) {
        self.open = open
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
        picked = machine
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
    /// - Returns: The tab's session id.
    @discardableResult
    func create(bindingId: String, deviceId: String, name: String) -> String {
        let sessionId = UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()
        tabs.append(
            TerminalTab(sessionId: sessionId, bindingId: bindingId, deviceId: deviceId, name: name, phase: .connecting))
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
            command(tab, verb: "resize", ["shell": .int(Int(stream.id)), "cols": .int(cols), "rows": .int(rows)])
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
        command(
            tab, verb: "persist",
            ["session_id": .string(sessionId), "is_persistent": .bool(isPersistent), "is_shared": .bool(isShared)])
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
        let args: [String: JSONValue] = [
            "module": .string("agent"), "verb": .string("stop_session"), "session_id": .string(tab.sessionId),
        ]
        switch open(tab.bindingId, Channel.kindCommand, args, false) {
        case .failure(let refusal):
            change(tab.sessionId) { $0.note = refusal }
        case .success(let stream):
            stream.whenClosed(timeout: Channel.streamTimeoutSeconds) { [weak self] result in
                switch result {
                case .failure(let refusal): self?.change(tab.sessionId) { $0.note = refusal }
                case .success: self?.remove(tab.sessionId)
                }
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
        stopDropping(sessionId)
        let before = tabs.firstIndex { $0.sessionId == sessionId } ?? 0
        tabs.removeAll { $0.sessionId == sessionId }
        if active == sessionId {
            active = tabs.isEmpty ? "" : tabs[min(before, tabs.count - 1)].sessionId
        }
    }

    private func attach(_ tab: TerminalTab, cols: Int, rows: Int) {
        let isResumed = tab.phase == .detached
        let args: [String: JSONValue] = [
            "device_id": .string(tab.deviceId),
            "cols": .int(cols),
            "rows": .int(rows),
            "session_id": .string(tab.sessionId),
            "is_resumed": .bool(isResumed),
        ]
        change(tab.sessionId) { $0.phase = .connecting }
        switch open(tab.bindingId, Channel.kindShell, args, true) {
        case .failure(let refusal):
            change(tab.sessionId) { tab in
                tab.phase = .detached
                tab.note = refusal
            }
        case .success(let stream):
            if isResumed {
                outputs[tab.sessionId] = nil
                onReplay?(tab.sessionId)
            }
            streams[tab.sessionId] = stream
            change(tab.sessionId) { tab in
                tab.phase = .open
                tab.note = nil
            }
            stream.onBytes = { [weak self, weak stream] data in
                self?.take(data, for: tab.sessionId)
                stream?.consumed(data.count)
            }
            stream.onEnd = { [weak self, weak stream] refusal in
                guard let self, let stream else { return }
                self.ended(tab.sessionId, stream: stream, refusal: refusal)
            }
        }
    }

    private func take(_ data: Data, for sessionId: String) {
        if isDropped(sessionId) { return }
        var kept = (outputs[sessionId] ?? Data()) + data
        if kept.count > TerminalPage.keptBytes { kept = kept.suffix(TerminalPage.keptBytes) }
        outputs[sessionId] = Data(kept)
        onOutput?(sessionId, data)
    }

    private func ended(_ sessionId: String, stream: ChannelStream, refusal: ClientError?) {
        if streams[sessionId] === stream { streams[sessionId] = nil }
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

    private func command(_ tab: TerminalTab, verb: String, _ args: [String: JSONValue]) {
        var all = args
        all["module"] = .string("agent")
        all["verb"] = .string(verb)
        guard case .success(let stream) = open(tab.bindingId, Channel.kindCommand, all, false) else { return }
        stream.whenClosed(timeout: Channel.streamTimeoutSeconds) { [weak self] result in
            if case .failure(let refusal) = result, verb != "resize" {
                self?.change(tab.sessionId) { $0.note = refusal }
            }
        }
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

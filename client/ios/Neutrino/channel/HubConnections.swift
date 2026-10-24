import Foundation

/// One session per hub this phone joined: joining, leaving, refreshing, and every hub's view. Every call runs on
/// the main queue.
final class HubConnections {
    private let store: BindingStore
    private let transport: HubTransport
    private let machine: ClientMachine
    private let clock: ClientClock
    private let resolveHubName: (@escaping (String?) -> Void) -> Void
    private let localNetworks: () -> [ChannelLocalNetwork]
    private let hasNetwork: () -> Bool
    private let onLeaving: (String) -> Void
    private var sessions: [String: HubSession] = [:]
    private var leaving: Set<String> = []
    private var jobErrors: [String: ClientError] = [:]
    private var isSuspended = false

    /// Called after every change of a hub's view or of the join.
    var onChange: (() -> Void)?

    /// The join a person started from the Join page.
    private(set) var join = HubJoin() {
        didSet { onChange?() }
    }

    /// Prepare the sessions.
    ///
    /// - Parameters:
    ///   - store: The bindings.
    ///   - transport: How hubs are reached.
    ///   - machine: What this phone says about itself.
    ///   - clock: The time and the timers.
    ///   - resolveHubName: Calls back with the IPv4 address `hub.neutrino.internal` resolves to here, or nil.
    ///   - localNetworks: The networks this phone holds an address in.
    ///   - hasNetwork: Whether the phone has a network at all.
    ///   - onLeaving: Called with a binding's id as its leave starts: its forwards and its terminals stop.
    init(
        store: BindingStore, transport: HubTransport, machine: ClientMachine, clock: ClientClock,
        resolveHubName: @escaping (@escaping (String?) -> Void) -> Void,
        localNetworks: @escaping () -> [ChannelLocalNetwork], hasNetwork: @escaping () -> Bool,
        onLeaving: @escaping (String) -> Void
    ) {
        self.store = store
        self.transport = transport
        self.machine = machine
        self.clock = clock
        self.resolveHubName = resolveHubName
        self.localNetworks = localNetworks
        self.hasNetwork = hasNetwork
        self.onLeaving = onLeaving
    }

    /// Every hub's view, in the order joined, each with its binding as the store keeps it now and its leave.
    var views: [HubView] {
        store.bindings.compactMap { binding in
            guard var view = sessions[binding.id]?.view else { return nil }
            view.binding = binding
            view.jobs.isLeaving = leaving.contains(binding.id)
            view.jobError = jobErrors[binding.id]
            return view
        }
    }

    /// Run one session per binding, following the store as bindings come and go. Of two or more bindings holding one
    /// hub id, the one joined last is kept and each other one ends as at a leave, its hub told.
    func start() {
        dropRepeatedHubs()
        store.onChange = { [weak self] bindings in self?.follow(bindings) }
        follow(store.bindings)
    }

    /// The session of one binding.
    ///
    /// - Parameter bindingId: The binding's id.
    /// - Returns: The session, or nil.
    func session(_ bindingId: String) -> HubSession? {
        sessions[bindingId]
    }

    /// Refresh every hub that can be: each one's error line goes, and each hub is asked again.
    ///
    /// - Returns: Whether any hub entered refreshing.
    @discardableResult
    func refresh() -> Bool {
        jobErrors = [:]
        let entered = store.bindings.compactMap { sessions[$0.id]?.refresh() }
        onChange?()
        return entered.contains(true)
    }

    /// Join the hub a pasted, opened or scanned link names; `join` says how it went.
    ///
    /// - Parameter text: The link's text.
    func startJoin(_ text: String) {
        if join.isJoining {
            ClientLog.info("a join is running; the second press is dropped")
            return
        }
        join = HubJoin(isJoining: true)
        do {
            let binding = try keep(try EnrollmentLink.parse(text))
            join = HubJoin(joinedId: binding.id)
        } catch let refusal as ClientError {
            join = HubJoin(refusal: refusal)
        } catch {
            join = HubJoin(refusal: .refusal(Channel.codeClientInternal, ["error": "\(error)"]))
        }
    }

    /// The Join page has drawn the join's end: it is forgotten.
    func clearJoin() {
        if !join.isJoining { join = HubJoin() }
    }

    /// Keep the binding a link names, its ticket unspent: the hub's session spends it at the first address that
    /// answers. A link whose ticket a binding already holds is that binding.
    ///
    /// - Parameter link: The link.
    /// - Returns: The binding kept.
    /// - Throws: `ClientError.refused` with `client_internal {error}` when the Keychain cannot be written.
    @discardableResult
    func keep(_ link: EnrollmentLink) throws -> HubBinding {
        if let held = store.bindings.first(where: { $0.ticket == link.ticket }) { return held }
        let binding = HubBinding(
            id: UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased(),
            name: machine.hostname,
            gatewayUrl: link.urls[0],
            gatewayUrls: link.urls,
            fingerprint: link.fingerprint,
            token: "",
            ticket: link.ticket,
            overlays: link.overlays)
        try store.put(binding)
        return binding
    }

    /// Leave one hub: this phone forgets the binding at once, then tells the hub once in the background, and the
    /// hub's answer changes nothing. A second press while the leave runs is dropped.
    ///
    /// - Parameter bindingId: The binding's id.
    func leave(_ bindingId: String) {
        if leaving.contains(bindingId) {
            ClientLog.info("a leave of \(bindingId) is running; the second press is dropped")
            return
        }
        guard let binding = store.get(bindingId) else { return }
        ClientLog.info("leaving the hub of \(bindingId): its binding is forgotten now")
        leaving.insert(bindingId)
        jobErrors[bindingId] = nil
        onChange?()
        onLeaving(bindingId)
        do {
            try store.remove(bindingId)
            if !binding.isPending { tellLeft(binding) }
        } catch let refusal as ClientError {
            jobErrors[bindingId] = refusal
        } catch {
            jobErrors[bindingId] = .refusal(Channel.codeClientInternal, ["error": "\(error)"])
        }
        leaving.remove(bindingId)
        onChange?()
    }

    /// Take a hub's binding back from a socket that replaced this one.
    ///
    /// - Parameter bindingId: The binding's id.
    func reconnect(_ bindingId: String) {
        sessions[bindingId]?.reconnect()
    }

    /// The phone's network changed: every session runs a round now.
    func networkChanged() {
        for session in sessions.values { session.networkChanged() }
    }

    /// The app is about to be suspended: every socket closes.
    func suspend() {
        isSuspended = true
        for session in sessions.values { session.suspend() }
    }

    /// The app came back to the foreground: every hub with no open socket runs a round now.
    func foreground() {
        isSuspended = false
        for session in sessions.values { session.foreground() }
    }

    private func tellLeft(_ binding: HubBinding) {
        var seen = Set<String>()
        let urls = ([binding.gatewayUrl] + binding.storedUrls).filter { !$0.isEmpty && seen.insert($0).inserted }
        let share = Channel.leaveTellTimeoutSeconds / Double(max(urls.count, 1))
        tellLeft(binding, urls: urls[...], share: share)
    }

    private func tellLeft(_ binding: HubBinding, urls: ArraySlice<String>, share: Double) {
        guard let url = urls.first else {
            ClientLog.info("the hub of \(binding.id) answered no leave in time")
            return
        }
        var isAnswered = false
        let next = urls.dropFirst()
        let timer = clock.schedule(after: share) { [weak self] in
            guard !isAnswered else { return }
            isAnswered = true
            self?.tellLeft(binding, urls: next, share: share)
        }
        transport.post(
            baseUrl: url, path: Channel.leavePath, fingerprint: binding.fingerprint,
            body: ChannelFrames.leaveRequest(binding: binding)
        ) { [weak self] result in
            guard !isAnswered else { return }
            isAnswered = true
            timer.cancel()
            switch result {
            case .success:
                ClientLog.info("the hub of \(binding.id) answered the leave: ok")
            case .failure(let refusal) where refusal.code == Channel.codeHubUnreachable:
                self?.tellLeft(binding, urls: next, share: share)
            case .failure(let refusal):
                ClientLog.info("the hub of \(binding.id) answered the leave: \(refusal.code)")
            }
        }
    }

    private func dropRepeatedHubs() {
        let dropped: [HubBinding]
        do {
            dropped = try store.dropRepeatedHubs()
        } catch {
            ClientLog.info("could not forget the repeated bindings here: \(error)")
            return
        }
        for held in dropped {
            ClientLog.info("dropped the binding \(held.id): a later one holds its hub")
            onLeaving(held.id)
            if !held.isPending { tellLeft(held) }
        }
    }

    private func joined(_ bindingId: String, hubBindingId: String) {
        replace(bindingId, isTold: false) { $0.boundId == hubBindingId }
    }

    private func welcomed(_ bindingId: String, hubId: String) {
        guard !hubId.isEmpty else { return }
        replace(bindingId, isTold: true) { $0.hubId == hubId }
    }

    private func replace(_ bindingId: String, isTold: Bool, isSameHub: (HubBinding) -> Bool) {
        guard store.get(bindingId) != nil else { return }
        for held in store.bindings where held.id != bindingId && isSameHub(held) {
            ClientLog.info("the join replaced the binding \(held.id) held here")
            onLeaving(held.id)
            guard (try? store.remove(held.id)) != nil else { continue }
            if isTold && !held.isPending { tellLeft(held) }
        }
    }

    private func follow(_ bindings: [HubBinding]) {
        let wanted = Set(bindings.map(\.id))
        for (id, session) in sessions where !wanted.contains(id) {
            session.stop()
            sessions[id] = nil
        }
        for binding in bindings where sessions[binding.id] == nil {
            let session = HubSession(
                bindingId: binding.id, store: store, transport: transport, machine: machine, clock: clock,
                resolveHubName: resolveHubName, localNetworks: localNetworks, hasNetwork: hasNetwork,
                onJoined: { [weak self] id, hubBindingId in self?.joined(id, hubBindingId: hubBindingId) },
                onWelcomed: { [weak self] id, hubId in self?.welcomed(id, hubId: hubId) })
            session.onChange = { [weak self] _ in self?.onChange?() }
            sessions[binding.id] = session
            session.start()
            if isSuspended { session.suspend() }
        }
        onChange?()
    }
}

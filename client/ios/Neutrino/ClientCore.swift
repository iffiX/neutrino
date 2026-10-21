import Combine
import Foundation

/// The app core: it holds the one state document every page draws from, pushes each change of it whole, and
/// runs every action a page starts. Every call runs on the main queue.
final class ClientCore: ObservableObject {
    /// What this phone says about itself.
    let machine: ClientMachine

    /// `intl` or `cn`, as the build stamped it.
    let edition: String

    /// Every hub joined, in the order joined.
    @Published private(set) var hubs: [HubView] = []

    /// The join a person started from the Join page.
    @Published private(set) var joining = HubJoin()

    /// What each forwarded entry's row shows, by `<binding>/<entry>`.
    @Published private(set) var forwardRows: [String: ForwardRow] = [:]

    /// Every terminal tab, in the order made.
    @Published private(set) var terminalTabs: [TerminalTab] = []

    /// The terminal tab shown, empty for none.
    @Published private(set) var activeTab = ""

    /// The machine a new terminal opens on.
    @Published private(set) var pickedMachine: TerminalMachine?

    /// The tabs whose Clear is still dropping what arrives.
    @Published private(set) var clearingTabs: Set<String> = []

    /// The language and the palette.
    @Published private(set) var settings: ClientSettings

    /// The sentences of the chosen language.
    @Published private(set) var words: WordCatalog

    /// The page the in-app browser shows, nil while it is closed.
    @Published var browser: BrowserTarget?

    /// The shared desktops whose Connect runs, by `<binding>/<entry>`.
    @Published private(set) var desktopsConnecting: Set<String> = []

    /// The code each shared desktop's last Connect ended in, by `<binding>/<entry>`.
    @Published private(set) var desktopErrors: [String: ClientError] = [:]

    /// The desktop the open viewer shows, nil while no viewer is open.
    @Published private(set) var viewing: RemoteDesktopTarget?

    /// What the remote desktop viewer draws and sends input with.
    let remoteDesktop: RemoteDesktopCore

    /// The terminal tabs, which the Terminals page's views read the output of.
    let tabs: TerminalTabs

    private let store: BindingStore
    private let connections: HubConnections
    private let forwards: WebForwards
    private let desktops: RemoteDesktopSessions
    private let desktopChoices: RemoteDesktopChoiceStore
    private let settingsStore: ClientSettingsStore
    private let bundle: Bundle

    /// Start the app core.
    ///
    /// - Parameters:
    ///   - secrets: Where the bindings are kept.
    ///   - transport: How hubs are reached.
    ///   - clock: The time and the timers.
    ///   - defaults: Where the settings and the local port table are kept.
    ///   - device: The device's name, the system's version, the architecture and the app's version.
    ///   - edition: `intl` or `cn`.
    ///   - hasNetwork: Whether the phone has a network at all.
    ///   - resolveHubName: Calls back with the address `hub.neutrino.internal` resolves to here, or nil.
    ///   - localNetworks: The networks this phone holds an address in.
    ///   - remoteDesktop: What the remote desktop viewer draws and sends input with.
    ///   - bundle: Where the word catalogs are.
    init(
        secrets: SecretStore, transport: HubTransport, clock: ClientClock, defaults: UserDefaults,
        device: ClientDevice, edition: String, hasNetwork: @escaping () -> Bool,
        resolveHubName: @escaping (@escaping (String?) -> Void) -> Void,
        localNetworks: @escaping () -> [ChannelLocalNetwork], remoteDesktop: RemoteDesktopCore,
        bundle: Bundle = .main
    ) {
        let store = BindingStore(secrets: secrets)
        let machine = ClientMachine(
            machineId: store.machineId, hostname: device.name, arch: device.arch, osVersion: device.osVersion,
            version: device.appVersion)
        let settingsStore = ClientSettingsStore(defaults: defaults)
        let settings = settingsStore.settings
        self.store = store
        self.machine = machine
        self.edition = edition
        self.settingsStore = settingsStore
        self.settings = settings
        self.bundle = bundle
        self.remoteDesktop = remoteDesktop
        words = WordCatalog.load(language: settings.language, bundle: bundle)
        var leaving: ((String) -> Void)?
        let connections = HubConnections(
            store: store, transport: transport, machine: machine, clock: clock, resolveHubName: resolveHubName,
            localNetworks: localNetworks, hasNetwork: hasNetwork, onLeaving: { leaving?($0) })
        self.connections = connections
        let forwards = WebForwards(
            table: LocalPortTable(defaults: defaults),
            openConnect: { bindingId, args in
                connections.session(bindingId)?.openStream(kind: Channel.kindConnect, args: args, hasBytes: true)
                    ?? .failure(.refusal(Channel.codeHubUnreachable, ["detail": "this hub is not connected"]))
            },
            material: { bindingId, args, completion in
                guard let session = connections.session(bindingId) else {
                    completion(.failure(.refusal(Channel.codeHubUnreachable, ["detail": "this hub is not connected"])))
                    return
                }
                session.openService(args: args, completion: completion)
            })
        self.forwards = forwards
        let desktopChoices = RemoteDesktopChoiceStore(defaults: defaults)
        self.desktopChoices = desktopChoices
        desktops = RemoteDesktopSessions(
            material: { bindingId, entryId, completion in
                guard let session = connections.session(bindingId) else {
                    completion(.failure(.refusal(Channel.codeHubUnreachable, ["detail": "this hub is not connected"])))
                    return
                }
                session.openService(args: ["id": .string(entryId)], completion: completion)
            },
            forward: { bindingId, entryId, port in forwards.hold(bindingId: bindingId, entryId: entryId, port: port) },
            release: { bindingId, entryId in forwards.release(bindingId: bindingId, entryId: entryId) },
            choiceOf: { desktopChoices.choice(of: $0) })
        tabs = TerminalTabs(
            open: { bindingId, kind, args, hasBytes in
                connections.session(bindingId)?.openStream(kind: kind, args: args, hasBytes: hasBytes)
                    ?? .failure(.refusal(Channel.codeHubUnreachable, ["detail": "this hub is not connected"]))
            },
            clock: clock)
        leaving = { [weak self] bindingId in self?.leaving(bindingId) }
        connections.onChange = { [weak self] in self?.hubsChanged() }
        forwards.onChange = { [weak self] in self?.forwardsChanged() }
        desktops.onChange = { [weak self] in self?.desktopsChanged() }
        tabs.onChange = { [weak self] in self?.tabsChanged() }
        connections.start()
    }

    /// Join the hub a pasted, opened or scanned link names.
    ///
    /// - Parameter link: The link's text.
    func join(_ link: String) {
        connections.startJoin(link)
    }

    /// The Join page has drawn the join's end.
    func clearJoin() {
        connections.clearJoin()
    }

    /// Leave one hub.
    ///
    /// - Parameter bindingId: The binding's id.
    func leave(_ bindingId: String) {
        connections.leave(bindingId)
    }

    /// Take a hub's binding back from a socket that replaced this one.
    ///
    /// - Parameter bindingId: The binding's id.
    func reconnect(_ bindingId: String) {
        connections.reconnect(bindingId)
    }

    /// Refresh every hub: every error line goes, and every hub is asked again.
    func refresh() {
        forwards.clearErrors()
        desktops.clearErrors()
        connections.refresh()
    }

    /// Whether any hub refreshes now, which disables the refresh button.
    var isRefreshing: Bool { hubs.contains { $0.jobs.isRefreshing } }

    /// Press Open on a web entry: its forward, its token when it needs one, then the in-app browser.
    ///
    /// - Parameters:
    ///   - bindingId: The hub.
    ///   - entry: The entry.
    func openWeb(bindingId: String, entry: ChannelServiceEntry) {
        forwards.open(
            bindingId: bindingId, entryId: entry.id, url: entry.payload.text("url"),
            isTokenRequired: entry.payload.flag("is_token_required")
        ) { [weak self] url in
            self?.browser = BrowserTarget(bindingId: bindingId, url: url, title: entry.title)
        }
    }

    /// Press Disconnect on a forwarded web entry.
    ///
    /// - Parameters:
    ///   - bindingId: The hub.
    ///   - entryId: The entry.
    func disconnectWeb(bindingId: String, entryId: String) {
        forwards.disconnect(bindingId: bindingId, entryId: entryId)
    }

    /// One web entry's local port, as its Configure dialog opens on it.
    ///
    /// - Parameters:
    ///   - bindingId: The hub.
    ///   - entryId: The entry.
    /// - Returns: The choice.
    func localPort(bindingId: String, entryId: String) -> LocalPortChoice {
        forwards.choice(bindingId: bindingId, entryId: entryId)
    }

    /// Save a web entry's Configure dialog.
    ///
    /// - Parameters:
    ///   - bindingId: The hub.
    ///   - entryId: The entry.
    ///   - choice: Automatic, or fixed with its number.
    /// - Throws: `ClientError.refused` with the code the dialog words as `ui.reason.<code>`.
    func configureLocalPort(bindingId: String, entryId: String, choice: LocalPortChoice) throws {
        try forwards.configure(bindingId: bindingId, entryId: entryId, choice: choice)
    }

    /// Press Panel on a hub's row: a sign-in token, the panel's forward, then the in-app browser.
    ///
    /// - Parameter bindingId: The hub.
    func openPanel(_ bindingId: String) {
        let title = hubs.first { $0.binding.id == bindingId }?.binding.title ?? ""
        forwards.openPanel(bindingId: bindingId) { [weak self] url in
            self?.browser = BrowserTarget(bindingId: bindingId, url: url, title: title)
        }
    }

    /// Press Connect on a shared desktop: its seat password, its forward, then the viewer on the forward.
    ///
    /// - Parameters:
    ///   - bindingId: The hub.
    ///   - entry: The entry.
    func connectDesktop(bindingId: String, entry: ChannelServiceEntry) {
        let hubName = hubs.first { $0.binding.id == bindingId }?.binding.title ?? ""
        desktops.connect(
            bindingId: bindingId, entryId: entry.id,
            name: hubName + ":" + (entry.deviceName.isEmpty ? entry.title : entry.deviceName),
            platformOs: entry.payload.text("platform_os"), port: entry.payload.number("port") ?? 0)
    }

    /// Close the viewer: its session and its forward end.
    func closeDesktop() {
        remoteDesktop.disconnect()
        desktops.close()
    }

    /// One shared desktop's codec and quality, as its Configure sheet opens on them.
    ///
    /// - Parameters:
    ///   - bindingId: The hub.
    ///   - entryId: The entry.
    /// - Returns: The kept choice.
    func desktopChoice(bindingId: String, entryId: String) -> RemoteDesktopChoice {
        desktopChoices.choice(of: RemoteDesktopSessions.key(bindingId, entryId))
    }

    /// Save a shared desktop's Configure sheet; the next Connect asks for the choice.
    ///
    /// - Parameters:
    ///   - bindingId: The hub.
    ///   - entryId: The entry.
    ///   - choice: The codec and the quality.
    func configureDesktop(bindingId: String, entryId: String, choice: RemoteDesktopChoice) {
        desktopChoices.keep(RemoteDesktopSessions.key(bindingId, entryId), choice)
    }

    /// Keep new settings and draw every page in them.
    ///
    /// - Parameter settings: The language and the palette.
    func save(_ settings: ClientSettings) {
        settingsStore.save(settings)
        if settings.language != self.settings.language {
            words = WordCatalog.load(language: settings.language, bundle: bundle)
        }
        self.settings = settings
    }

    /// The phone's network changed: every hub runs a round now.
    func networkChanged() {
        connections.networkChanged()
    }

    /// The time iOS gives the app in the background is ending: the viewer closes with its forward, every channel
    /// closes and every forward's listener stops.
    func suspend() {
        closeDesktop()
        forwards.suspend()
        connections.suspend()
    }

    /// The app came back to the foreground: every hub reconnects at once and every forward listens again on its
    /// number.
    func foreground() {
        connections.foreground()
        forwards.foreground()
    }

    /// Pick the machine a new terminal opens on.
    ///
    /// - Parameter machine: The machine.
    func pickMachine(_ machine: TerminalMachine) {
        tabs.pick(machine)
    }

    /// Press New terminal on the picked machine.
    func newTerminal() {
        guard let picked = pickedMachine,
            let machine = hubs.first(where: { $0.binding.id == picked.bindingId })?.terminals.first(where: {
                $0.deviceId == picked.deviceId
            })
        else { return }
        tabs.create(bindingId: picked.bindingId, deviceId: picked.deviceId, name: machine.name)
    }

    private func leaving(_ bindingId: String) {
        if browser?.bindingId == bindingId { browser = nil }
        if viewing?.key.hasPrefix("\(bindingId)/") == true { remoteDesktop.disconnect() }
        desktops.forget(bindingId: bindingId)
        desktopChoices.forget(bindingId: bindingId)
        forwards.forget(bindingId: bindingId)
        tabs.forget(bindingId: bindingId)
    }

    private func hubsChanged() {
        let views = connections.views
        forwards.take(views)
        tabs.take(views)
        joining = connections.join
        hubs = merged(views)
    }

    private func forwardsChanged() {
        forwardRows = forwards.rows
        hubs = merged(connections.views)
    }

    private func desktopsChanged() {
        desktopsConnecting = desktops.connecting
        desktopErrors = desktops.errors
        viewing = desktops.viewing
    }

    private func tabsChanged() {
        terminalTabs = tabs.tabs
        activeTab = tabs.active
        pickedMachine = tabs.picked
        clearingTabs = tabs.clearing
    }

    private func merged(_ views: [HubView]) -> [HubView] {
        views.map { view in
            guard let row = forwards.rows[WebForwards.panelKey(view.binding.id)] else { return view }
            var next = view
            next.jobs.isOpeningPanel = row.job == .opening
            if next.jobError == nil { next.jobError = row.error }
            return next
        }
    }
}

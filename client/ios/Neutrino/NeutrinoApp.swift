import SwiftUI
import UIKit

/// The app: one app core for its life, the network watched, the background followed, and the shell drawn.
@main
struct NeutrinoApp: App {
    @StateObject private var core: ClientCore
    @StateObject private var arm = ArmState()
    @Environment(\.scenePhase) private var scenePhase
    private let cache: TerminalViewCache
    private let network: ClientNetworkMonitor
    private let background: ClientBackground

    init() {
        let network = ClientNetworkMonitor()
        let info = Bundle.main.infoDictionary ?? [:]
        let edition = (info[Client.editionInfoKey] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? Client.editionIntl
        let device = ClientDevice(
            name: UIDevice.current.name,
            arch: Self.architecture,
            osVersion: UIDevice.current.systemVersion,
            appVersion: info["CFBundleShortVersionString"] as? String ?? "")
        let core = ClientCore(
            secrets: KeychainSecretStore(service: Client.keychainService),
            transport: URLSessionHubTransport(),
            clock: SystemClientClock(),
            defaults: .standard,
            device: device,
            edition: edition,
            hasNetwork: { network.hasNetwork },
            resolveHubName: HubNameResolver.resolve,
            localNetworks: ChannelLocalNetwork.deviceNetworks,
            remoteDesktop: Self.remoteDesktopCore())
        network.onChange = { [weak core] in core?.networkChanged() }
        network.start()
        _core = StateObject(wrappedValue: core)
        self.network = network
        cache = TerminalViewCache(tabs: core.tabs)
        background = ClientBackground(core: core)
    }

    var body: some Scene {
        WindowGroup {
            ThemedRoot(core: core, cache: cache).environmentObject(arm)
        }
        .onChange(of: scenePhase) { phase in
            switch phase {
            case .background: background.entered()
            case .active: background.returned()
            default: break
            }
        }
    }

    private static func remoteDesktopCore() -> RemoteDesktopCore {
        guard RustDeskNative.isLinked,
            let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
        else { return MissingRemoteDesktopCore() }
        let directory = support.appendingPathComponent(RemoteDesktop.coreDirectory, isDirectory: true)
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        return RustDeskRemoteDesktopCore(appDir: directory.path)
    }

    private static var architecture: String {
        #if arch(arm64)
            return "arm64"
        #else
            return "amd64"
        #endif
    }
}

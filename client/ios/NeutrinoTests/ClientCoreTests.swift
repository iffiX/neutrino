import Darwin
import XCTest

@testable import Neutrino

final class ClientCoreTests: XCTestCase {
    private var transport = FakeTransport()
    private var clock = FakeClientClock()
    private var desktop = FakeRemoteDesktopCore()
    private var defaults = UserDefaults()
    private var suite = ""
    private var share = FakeShareClient()

    override func setUp() {
        transport = FakeTransport()
        transport.answer = { line in
            switch line.text("command") {
            case "join": return ["binding_id": .string("hub-binding"), "token": .string("tok")]
            case "forward_start": return ["listen": line["listen"] ?? .string("")]
            default: return [:]
            }
        }
        clock = FakeClientClock()
        desktop = FakeRemoteDesktopCore()
        share = FakeShareClient()
        suite = "neutrino.tests.\(UUID().uuidString)"
        defaults = UserDefaults(suiteName: suite) ?? .standard
    }

    override func tearDown() {
        defaults.removePersistentDomain(forName: suite)
    }

    private func core() -> ClientCore {
        let fake = transport
        let client = ClientTransport(library: fake, directory: "/data", dialerOf: { _ in fake }, clock: clock)
        return ClientCore(
            secrets: FakeSecretStore(), transport: client, clock: clock, defaults: defaults, device: Samples.device,
            edition: Client.editionIntl, hasNetwork: { true }, resolveHubName: { $0(nil) }, localNetworks: { [] },
            shareClient: { self.share }, remoteDesktop: desktop, bundle: Bundle(for: ClientCore.self))
    }

    private static let services: [JSONValue] = [
        .object([
            "id": .string("gitea"), "type": .string("web"), "title": .string("Gitea"),
            "payload": .object(["url": .string("http://10.0.0.5:3000/explore")]),
            "source": .string("module"), "app_id": .string("gitea"), "local_port": .int(24001),
        ]),
        .object([
            "id": .string("gitea_ssh"), "type": .string("ssh"), "title": .string("Gitea SSH"),
            "payload": .object(["host": .string("10.0.0.5"), "port": .int(22)]),
            "source": .string("module"), "app_id": .string("gitea"), "local_port": .int(24002),
        ]),
        .object([
            "id": .string("desk"), "type": .string("rdp"), "title": .string("Desk"),
            "payload": .object([
                "host": .string("10.0.0.7"), "port": .int(21118), "platform_os": .string("linux"),
            ]),
            "source": .string("device"), "device_name": .string("argon"),
        ]),
        .object([
            "id": .string("music"), "type": .string("file"), "title": .string("music"),
            "payload": .object([
                "protocol": .string("smb"), "host": .string("10.0.0.5"), "share": .string("music"),
                "users": .array([.string("alice")]),
            ]),
            "source": .string("module"),
        ]),
    ]

    private static let apps: [JSONValue] = [
        .object([
            "id": .string("gitea"), "title": .string("Gitea"), "source": .string("module"),
            "local_name": .string("gitea.home.localhost"),
        ])
    ]

    private func joinAndConnect(_ core: ClientCore) throws -> String {
        core.join(
            Samples.link([
                "urls": .array([.string("tcp://192.168.1.1:8443")]), "token": .string("TICKET"),
                "key": .string(Samples.hubKey), "role": .string("client"),
            ]))
        let id = try XCTUnwrap(core.joining.joinedId)
        XCTAssertTrue(RunLoopWait.until { !self.transport.sent("dial").isEmpty })
        transport.event("session_open", id, ["address": .string("tcp://192.168.1.1:8443"), "path": .string("lan")])
        XCTAssertTrue(RunLoopWait.until { !self.transport.written("hello").isEmpty })
        transport.frame(id, Samples.welcome)
        transport.frame(id, Samples.state(["services": .array(Self.services), "apps": .array(Self.apps)]))
        XCTAssertTrue(
            RunLoopWait.until { core.hubs.first?.connection == .connected && core.hubs.first?.apps.count == 1 })
        return id
    }

    private func isListening(_ port: Int) -> Bool {
        let descriptor = socket(AF_INET, SOCK_STREAM, 0)
        defer { close(descriptor) }
        var address = sockaddr_in()
        address.sin_len = UInt8(MemoryLayout<sockaddr_in>.size)
        address.sin_family = sa_family_t(AF_INET)
        address.sin_port = in_port_t(UInt16(port).bigEndian)
        address.sin_addr = in_addr(s_addr: inet_addr("127.0.0.1"))
        let connected = withUnsafePointer(to: &address) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) {
                connect(descriptor, $0, socklen_t(MemoryLayout<sockaddr_in>.size))
            }
        }
        return connected == 0
    }

    private func turnMainQueue() {
        RunLoop.main.run(until: Date().addingTimeInterval(0.2))
    }

    func testAJoinKeepsTheBindingAndTheHubsRowConnectsOnItsFirstRound() throws {
        let core = self.core()
        _ = try joinAndConnect(core)
        XCTAssertEqual(core.hubs.count, 1)
        XCTAssertEqual(core.hubs.first?.connection, .connected)
        XCTAssertEqual(core.hubs.first?.binding.hubName, "Home")
        let join = try XCTUnwrap(transport.sent("join").first)
        XCTAssertEqual(join.text("hub_key"), Samples.hubKey)
        XCTAssertEqual(join.text("ticket"), "TICKET")
    }

    func testUseForwardsAnAppAtTheHubsPortsAndOpenOpensItsPageOnTheLoopback() throws {
        let core = self.core()
        let id = try joinAndConnect(core)
        let hub = try XCTUnwrap(core.hubs.first)
        let app = try XCTUnwrap(hub.apps.first)
        core.useApp(bindingId: id, app: app)
        XCTAssertTrue(RunLoopWait.until { core.forwardRows[AppForwards.key(id, "gitea")]?.isInUse == true })
        XCTAssertNil(core.browser)
        core.openApp(bindingId: id, app: app)
        XCTAssertTrue(RunLoopWait.until { core.browser != nil })
        let starts = transport.sent("forward_start")
        XCTAssertEqual(starts.map { $0.text("listen") }, ["127.0.0.1:24001"])
        XCTAssertEqual(starts.first?.object("open").text("id"), "gitea")
        XCTAssertEqual(starts.first?.object("open").text("kind"), "connect")
        XCTAssertEqual(core.browser?.url, "http://127.0.0.1:24001/explore")
        let row = try XCTUnwrap(core.forwardRows[AppForwards.key(id, "gitea")])
        XCTAssertTrue(row.isInUse)
        XCTAssertNil(row.job)
        core.stopApp(bindingId: id, appId: "gitea")
        XCTAssertTrue(RunLoopWait.until { !self.transport.sent("forward_stop").isEmpty })
        XCTAssertEqual(transport.sent("forward_stop").first?.text("listen"), "127.0.0.1:24001")
    }

    func testTheEndOfTheBackgroundTimeStopsEveryListenerAndTheReturnListensAgainOnTheSamePort() throws {
        let core = self.core()
        let id = try joinAndConnect(core)
        let hub = try XCTUnwrap(core.hubs.first)
        core.useApp(bindingId: id, app: try XCTUnwrap(hub.apps.first))
        XCTAssertTrue(RunLoopWait.until { core.forwardRows[AppForwards.key(id, "gitea")]?.isInUse == true })

        core.suspend()
        XCTAssertTrue(RunLoopWait.until { !self.transport.sent("forward_stop").isEmpty })
        XCTAssertTrue(RunLoopWait.until { !self.transport.sent("undial").isEmpty })

        core.foreground()
        XCTAssertTrue(RunLoopWait.until { self.transport.sent("forward_start").count == 2 })
        XCTAssertEqual(transport.sent("forward_start").last?.text("listen"), "127.0.0.1:24001")
        XCTAssertTrue(RunLoopWait.until { self.transport.sent("dial").count == 2 })
        XCTAssertEqual(core.forwardRows[AppForwards.key(id, "gitea")]?.isInUse, true)
    }

    private func openDesktop(_ core: ClientCore, id: String) throws -> RemoteDesktopTarget {
        let hub = try XCTUnwrap(core.hubs.first)
        core.connectDesktop(bindingId: id, entry: try XCTUnwrap(hub.services(of: "rdp").first))
        XCTAssertEqual(core.desktopsConnecting, ["\(id)/desk"])
        XCTAssertTrue(RunLoopWait.until { !self.transport.written("service").isEmpty })
        let service = try XCTUnwrap(transport.written("service").last)
        XCTAssertEqual(service.text("id"), "desk")
        transport.frame(
            id,
            [
                "type": .string("reply"), "request": service["request"] ?? .string(""),
                "params": .object(["password": .string("seat")]),
            ])
        XCTAssertTrue(RunLoopWait.until { core.viewing != nil })
        XCTAssertEqual(core.desktopsConnecting, [])
        return try XCTUnwrap(core.viewing)
    }

    func testConnectOnADesktopOpensTheViewerOnAForwardOfItsOwn() throws {
        let core = self.core()
        let id = try joinAndConnect(core)
        let target = try openDesktop(core, id: id)
        XCTAssertEqual(target.name, "Home:argon")
        XCTAssertEqual(target.password, "seat")
        XCTAssertEqual(target.platformOs, "linux")
        XCTAssertEqual(target.host, "127.0.0.1")
        XCTAssertTrue(isListening(target.port))
        XCTAssertNil(core.forwardRows[target.key])

        core.closeDesktop()
        turnMainQueue()
        XCTAssertNil(core.viewing)
        XCTAssertEqual(desktop.disconnects, 1)
        XCTAssertFalse(isListening(target.port))
    }

    func testTheEndOfTheBackgroundTimeClosesTheViewerForGood() throws {
        let core = self.core()
        let id = try joinAndConnect(core)
        let target = try openDesktop(core, id: id)

        core.suspend()
        turnMainQueue()
        XCTAssertNil(core.viewing)
        XCTAssertEqual(desktop.disconnects, 1)
        XCTAssertFalse(isListening(target.port))

        core.foreground()
        turnMainQueue()
        XCTAssertNil(core.viewing)
        XCTAssertFalse(isListening(target.port))
    }

    func testTheEndOfTheBackgroundTimeCutsAShareTransferAndTheReturnLogsInAgain() throws {
        let core = self.core()
        _ = try joinAndConnect(core)
        let hub = try XCTUnwrap(core.hubs.first)
        var target = try XCTUnwrap(ShareTarget.of(hub, try XCTUnwrap(hub.services(of: "file").first)))
        target.isDeclared = true
        share.files = ["song.mp3": Data("la la".utf8)]
        core.shares.logIn(target, login: ShareLogin(user: "alice", password: "pw"), isKept: true)
        XCTAssertEqual(core.share?.items.map(\.name), ["song.mp3"])
        share.isHolding = true
        core.shares.session?.open(try XCTUnwrap(core.share?.items.first))
        XCTAssertEqual(core.share?.transfers["song.mp3"]?.isRunning, true)

        core.suspend()
        XCTAssertTrue(share.isDisconnected)
        share.finish(POSIXError(.ENOTCONN))
        XCTAssertEqual(core.share?.transfers["song.mp3"]?.error?.code, "share_interrupted")

        core.foreground()
        XCTAssertFalse(share.isDisconnected)
        XCTAssertEqual(core.share?.items.map(\.name), ["song.mp3"])
        share.isHolding = false
        core.shares.session?.retry("song.mp3")
        XCTAssertNil(core.share?.transfers["song.mp3"])
        XCTAssertNotNil(core.share?.preview)
        core.shares.back()
        XCTAssertNil(core.share)
        turnMainQueue()
    }

    func testLeavingAHubForgetsItsBindingAtOnceAndTellsTheHubThroughTheTransport() throws {
        let core = self.core()
        let id = try joinAndConnect(core)
        core.leave(id)
        XCTAssertTrue(core.hubs.isEmpty)
        XCTAssertTrue(RunLoopWait.until { !self.transport.sent("leave").isEmpty })
        XCTAssertEqual(transport.sent("leave").first?.text("hub_key"), Samples.hubKey)
    }
}

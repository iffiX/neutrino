import XCTest

@testable import Neutrino

final class AppForwardsTests: XCTestCase {
    private var defaults = UserDefaults()
    private var suite = ""
    private var forwarder = FakeLocalForwarder()
    private var clock = FakeClientClock()
    private var busy: Set<Int> = []
    private var material: Result<[String: JSONValue], ClientError> = .success(["token": .string("one-time")])
    private var asked: [[String: JSONValue]] = []
    private var opened: [String] = []
    private var forwards: AppForwards?

    private let app = ChannelApp(
        id: "gitea_d1", title: "Gitea", source: "module", deviceId: "d1", deviceName: "lab",
        localName: "gitea.lab.localhost")

    override func setUp() {
        suite = "neutrino.tests.\(UUID().uuidString)"
        defaults = UserDefaults(suiteName: suite) ?? .standard
        forwarder = FakeLocalForwarder()
        clock = FakeClientClock()
        busy = []
        asked = []
        opened = []
        material = .success(["token": .string("one-time")])
        forwards = AppForwards(
            table: LocalPortTable(defaults: defaults, isFree: { port, _, _ in !self.busy.contains(port) }),
            forwarder: forwarder, clock: clock,
            material: { _, args, completion in
                self.asked.append(args)
                completion(self.material)
            })
    }

    override func tearDown() {
        defaults.removePersistentDomain(forName: suite)
    }

    private func entry(
        _ id: String, _ type: String, _ payload: [String: JSONValue], port: Int, appId: String = "gitea_d1"
    ) -> ChannelServiceEntry {
        var object: [String: JSONValue] = [
            "id": .string(id), "type": .string(type), "title": .string("Gitea"), "payload": .object(payload),
            "source": .string("module"), "app_id": .string(appId), "name": .string(id), "local_port": .int(port),
        ]
        object["device_id"] = .string("d1")
        return ChannelServiceEntry.of(.object(object))!
    }

    private func hub(_ services: [ChannelServiceEntry]) -> HubView {
        var hub = HubView(binding: Samples.binding)
        hub.connection = .connected
        hub.connectedAddress = "tcp://192.168.1.1:8443"
        hub.isPanelAllowed = true
        hub.services = services
        hub.apps = [app]
        return hub
    }

    private var gitea: [ChannelServiceEntry] {
        [
            entry("gitea_d1_web", "web", ["url": .string("http://10.0.0.5:3000/explore?tab=1")], port: 27311),
            entry("gitea_d1_ssh", "port", ["port": .int(22)], port: 30418),
            entry("ssh_server_d1_iffi", "ssh", ["port": .int(2201)], port: 24555),
        ]
    }

    func testTheSshServerHasNoEntryToShowAndSoNoRow() {
        let server = ChannelApp(
            id: "ssh_server_d1", title: "SSH", source: "module", deviceId: "d1", deviceName: "lab",
            localName: "ssh.lab.localhost")
        let shell = entry("ssh_server_d1_iffi", "ssh", ["port": .int(2201)], port: 24555, appId: "ssh_server_d1")
        var shells = hub([shell])
        shells.apps = [server]
        XCTAssertTrue(AppForwards.entries(of: shells, app: server).isEmpty)
    }

    func testUseForwardsEveryEntryAndOpensNothing() throws {
        let forwards = try XCTUnwrap(self.forwards)
        forwards.use(hub: hub(gitea), app: app)
        XCTAssertEqual(forwarder.started.map(\.port), [27311, 30418])
        XCTAssertEqual(forwarder.started.map { $0.open.text("id") }, ["gitea_d1_web", "gitea_d1_ssh"])
        XCTAssertEqual(forwarder.started.map { $0.open.text("kind") }, ["connect", "connect"])
        XCTAssertEqual(forwards.rows["b1/gitea_d1"]?.isInUse, true)
        XCTAssertTrue(asked.isEmpty)
    }

    func testOpenOpensThePageOfAnAppInUseOnTheLoopback() throws {
        let forwards = try XCTUnwrap(self.forwards)
        forwards.open(hub: hub(gitea), app: app) { self.opened.append($0) }
        XCTAssertTrue(opened.isEmpty)
        forwards.use(hub: hub(gitea), app: app)
        forwards.open(hub: hub(gitea), app: app) { self.opened.append($0) }
        XCTAssertEqual(opened, ["http://127.0.0.1:27311/explore?tab=1"])
        XCTAssertEqual(forwarder.started.count, 2)
        XCTAssertTrue(asked.isEmpty)
    }

    func testATokenPageOpensWithAFreshTokenAtEachOpen() throws {
        let forwards = try XCTUnwrap(self.forwards)
        let page = entry(
            "gitea_d1_web", "web", ["url": .string("http://10.0.0.5:8000/"), "is_token_required": .bool(true)],
            port: 27311)
        forwards.use(hub: hub([page]), app: app)
        forwards.open(hub: hub([page]), app: app) { self.opened.append($0) }
        forwards.open(hub: hub([page]), app: app) { self.opened.append($0) }
        XCTAssertEqual(opened, Array(repeating: "http://127.0.0.1:27311/?tkn=one-time", count: 2))
        XCTAssertEqual(forwarder.started.count, 1)
        XCTAssertEqual(asked.count, 2)
    }

    func testAnEntryWithNoNumberGetsNoForwardUntilOneComes() throws {
        let forwards = try XCTUnwrap(self.forwards)
        let bare = entry("gitea_d1_ssh", "port", ["port": .int(22)], port: 0)
        forwards.use(hub: hub([gitea[0], bare]), app: app)
        XCTAssertEqual(forwarder.started.map(\.port), [27311])
        XCTAssertNil(forwards.rows["b1/gitea_d1"]?.error)
    }

    func testATakenNumberFailsAndTheRestStayUp() throws {
        busy = [30418]
        let forwards = try XCTUnwrap(self.forwards)
        forwards.use(hub: hub(gitea), app: app)
        let row = try XCTUnwrap(forwards.rows["b1/gitea_d1"])
        XCTAssertEqual(row.error?.code, "port_taken")
        XCTAssertEqual(row.error?.wordParams["port"], "30418")
        XCTAssertEqual(forwarder.started.map(\.port), [27311])
        XCTAssertTrue(row.isInUse)
    }

    func testStopEndsEveryForwardOfTheApp() throws {
        let forwards = try XCTUnwrap(self.forwards)
        forwards.use(hub: hub(gitea), app: app)
        forwards.stop(bindingId: "b1", appId: "gitea_d1")
        XCTAssertEqual(Set(forwarder.stopped.map(\.port)), [27311, 30418])
        XCTAssertNil(forwards.rows["b1/gitea_d1"])
    }

    func testConfigureKeepsANumberAndIsRefusedWhileTheAppIsInUse() throws {
        let forwards = try XCTUnwrap(self.forwards)
        let hubs = [hub(gitea)]
        try forwards.configure(hubs: hubs, bindingId: "b1", appId: "gitea_d1", numbers: ["gitea_d1_web": 28080])
        XCTAssertEqual(forwards.port(bindingId: "b1", entry: gitea[0]), 28080)
        XCTAssertThrowsError(
            try forwards.configure(hubs: hubs, bindingId: "b1", appId: "gitea_d1", numbers: ["gitea_d1_web": 30418])
        ) { error in XCTAssertEqual((error as? ClientError)?.code, "port_taken") }
        forwards.use(hub: hubs[0], app: app)
        XCTAssertEqual(forwarder.started.first?.port, 28080)
        XCTAssertThrowsError(
            try forwards.configure(hubs: hubs, bindingId: "b1", appId: "gitea_d1", numbers: ["gitea_d1_web": nil])
        ) { error in XCTAssertEqual((error as? ClientError)?.code, "disconnect_first") }
    }

    func testPanelSignsInAtAPickedPortOnTheLoopback() throws {
        let forwards = try XCTUnwrap(self.forwards)
        forwards.openPanel(bindingId: "b1") { self.opened.append($0) }
        XCTAssertEqual(opened, ["http://127.0.0.1:20000/?tkn=one-time"])
        XCTAssertEqual(forwarder.started.first?.open["is_panel"], .bool(true))
        XCTAssertEqual(forwards.rows["b1/#panel"]?.localPort, 20000)
        XCTAssertEqual(asked.first?["is_panel"], .bool(true))
    }

    func testAWithdrawnEntryOrALeftHubStopsForwards() throws {
        let forwards = try XCTUnwrap(self.forwards)
        forwards.use(hub: hub(gitea), app: app)
        forwards.take([hub([gitea[0]])])
        XCTAssertEqual(forwarder.stopped.map(\.port), [30418])
        forwards.take([])
        XCTAssertEqual(forwarder.stopped.map(\.port), [30418, 27311])
    }

    func testASuspendStopsEveryListenerAndTheForegroundListensAgainOnItsNumber() throws {
        let forwards = try XCTUnwrap(self.forwards)
        forwards.use(hub: hub(gitea), app: app)
        forwards.suspend()
        XCTAssertEqual(Set(forwarder.stopped.map(\.port)), [27311, 30418])
        forwards.foreground()
        XCTAssertEqual(forwarder.started.map(\.port).sorted(), [27311, 27311, 30418, 30418])
    }

    func testAUdpForwardTheHubEndedIsStartedAgainWhileItsAppIsInUse() throws {
        let forwards = try XCTUnwrap(self.forwards)
        let udp = entry("gitea_d1_7777_udp", "port", ["port": .int(7777), "protocol": .string("udp")], port: 25001)
        forwards.use(hub: hub([udp]), app: app)
        XCTAssertEqual(forwarder.started.map(\.protocol), ["udp"])
        forwards.ended(
            TransportForwardEnd(
                listen: "127.0.0.1:25001", protocol: "udp", refusal: .refusal("agent_offline", ["device": "lab"])))
        XCTAssertEqual(forwards.rows["b1/gitea_d1"]?.error?.code, "agent_offline")
        clock.advance(by: Forward.udpRestartSeconds)
        XCTAssertEqual(forwarder.started.count, 2)
    }
}

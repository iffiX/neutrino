import XCTest

@testable import Neutrino

final class ShareSessionsTests: XCTestCase {
    private var transport = FakeTransport()
    private var secrets = FakeSecretStore()
    private var client = FakeShareClient()
    private var sessions: ShareSessions?
    private var material: Result<[String: JSONValue], ClientError> = .success([
        "user": .string("smb_iffi"), "password": .string("generated"),
    ])
    private var asked = 0
    private var directory = FileManager.default.temporaryDirectory

    private let target = ShareTarget(
        bindingId: "b1", entryId: "samba_dev_music", title: "music", share: "music", users: ["alice", "bob"],
        isDeclared: true)

    private let machine = ShareTarget(
        bindingId: "b1", entryId: "samba_box_home", title: "home", share: "home", users: [])

    override func setUp() {
        secrets = FakeSecretStore()
        client = FakeShareClient()
        directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        transport = FakeTransport()
        _ = try? transport.start(directory: "/data", secret: String(repeating: "ee", count: 32))
        asked = 0
        sessions = ShareSessions(
            secrets: secrets, makeClient: { self.client },
            openConnect: { _, args in
                var open = args
                open["kind"] = .string(Channel.kindConnect)
                do {
                    return .success(
                        try TransportStream.open(
                            dialer: self.transport, secret: self.transport.secret, binding: "b1", open: open,
                            carriage: .raw))
                } catch {
                    return .failure(.refusal(Channel.codeHubUnreachable))
                }
            },
            material: { _, _, completion in
                self.asked += 1
                completion(self.material)
            },
            directory: directory)
    }

    override func tearDown() {
        sessions?.forget(bindingId: "b1")
        RunLoop.main.run(until: Date().addingTimeInterval(0.2))
        try? FileManager.default.removeItem(at: directory)
    }

    private func hub(services: [ChannelServiceEntry]) -> HubView {
        var hub = HubView(binding: Samples.binding)
        hub.connection = .connected
        hub.connectedAddress = "tcp://192.168.1.1:8443"
        hub.services = services
        return hub
    }

    private var entry: ChannelServiceEntry? {
        ChannelServiceEntry.of(
            .object([
                "id": .string("samba_dev_music"), "type": .string("file"), "title": .string("music"),
                "source": .string("declared"),
                "payload": .object([
                    "protocol": .string("smb"), "host": .string("10.0.0.5"), "share": .string("music"),
                    "users": .array([.string("alice"), .string("bob")]),
                ]),
            ]))
    }

    func testAFileEntryNamesItsShareAndItsUsers() throws {
        let hub = hub(services: [])
        XCTAssertEqual(ShareTarget.of(hub, try XCTUnwrap(entry)), target)
    }

    func testALoginTheShareTakesIsKeptInTheKeychainAndThePageOpensAtTheRoot() throws {
        let sessions = try XCTUnwrap(self.sessions)
        client.files = ["song.mp3": Data("la".utf8)]
        sessions.logIn(target, login: ShareLogin(user: "alice", password: "pw"), isKept: true)
        XCTAssertEqual(client.connected?.share, "music")
        XCTAssertEqual(client.connected?.login, ShareLogin(user: "alice", password: "pw"))
        XCTAssertEqual(sessions.heldLogins, [target.id])
        XCTAssertNotNil(secrets.items[SharePage.loginsAccount])
        XCTAssertEqual(sessions.session?.view.path, SharePath())
        XCTAssertEqual(sessions.session?.view.items.map(\.name), ["song.mp3"])
        XCTAssertNil(sessions.rows[target.id])
    }

    func testRememberOffHoldsTheLoginUntilTheAppQuits() throws {
        let sessions = try XCTUnwrap(self.sessions)
        sessions.logIn(target, login: ShareLogin(user: "bob", password: "pw"), isKept: false)
        XCTAssertEqual(sessions.heldLogins, [target.id])
        XCTAssertNil(secrets.items[SharePage.loginsAccount])
    }

    func testALoginTheShareRejectsIsNeitherKeptNorOpened() throws {
        let sessions = try XCTUnwrap(self.sessions)
        client.connectFailure = POSIXError(.ECONNREFUSED)
        sessions.logIn(target, login: ShareLogin(user: "alice", password: "typo"), isKept: true)
        XCTAssertEqual(sessions.rows[target.id]?.error?.code, "share_login_rejected")
        XCTAssertTrue(sessions.heldLogins.isEmpty)
        XCTAssertNil(secrets.items[SharePage.loginsAccount])
        XCTAssertNil(sessions.session)
        XCTAssertTrue(client.isDisconnected)
    }

    func testOpenWithAKeptLoginTheShareNowRejectsForgetsIt() throws {
        let sessions = try XCTUnwrap(self.sessions)
        sessions.logIn(target, login: ShareLogin(user: "alice", password: "old"), isKept: true)
        sessions.back()
        XCTAssertNil(sessions.session)
        client.connectFailure = POSIXError(.ECONNREFUSED)
        sessions.open(target)
        XCTAssertEqual(sessions.rows[target.id]?.error?.code, "share_login_rejected")
        XCTAssertTrue(sessions.heldLogins.isEmpty)
        XCTAssertNil(secrets.items[SharePage.loginsAccount])
    }

    func testForgetPasswordRemovesTheKeptLogin() throws {
        let sessions = try XCTUnwrap(self.sessions)
        sessions.logIn(target, login: ShareLogin(user: "alice", password: "pw"), isKept: true)
        sessions.back()
        sessions.forgetLogin(target.id)
        XCTAssertTrue(sessions.heldLogins.isEmpty)
        XCTAssertNil(secrets.items[SharePage.loginsAccount])
    }

    func testTheShareClosesWhenItsHubWithdrawsTheEntry() throws {
        let sessions = try XCTUnwrap(self.sessions)
        sessions.logIn(target, login: ShareLogin(user: "alice", password: "pw"), isKept: true)
        sessions.take([hub(services: [try XCTUnwrap(entry)])])
        XCTAssertNotNil(sessions.session)
        sessions.take([hub(services: [])])
        XCTAssertNil(sessions.session)
        XCTAssertTrue(client.isDisconnected)
    }

    func testEveryConnectionOfTheSharesForwardIsOneConnectStreamNamingTheEntry() throws {
        let sessions = try XCTUnwrap(self.sessions)
        var dialled: LoopbackClient?
        client.onConnect = { port in dialled = LoopbackClient(port: port) }
        sessions.logIn(target, login: ShareLogin(user: "alice", password: "pw"), isKept: true)
        XCTAssertNotNil(dialled)
        XCTAssertTrue(RunLoopWait.until { !self.transport.streams.isEmpty })
        let open = try XCTUnwrap(transport.streams.first?.open)
        XCTAssertEqual(open.text("kind"), "connect")
        XCTAssertEqual(open.text("id"), "samba_dev_music")
        RunLoopWait.turn()
        XCTAssertEqual(transport.streams.count, 1)
    }

    func testAPullWhileTheConnectionIsCarriedReadsTheFolderAlone() throws {
        let sessions = try XCTUnwrap(self.sessions)
        var dialled: LoopbackClient?
        client.onConnect = { port in dialled = LoopbackClient(port: port) }
        sessions.logIn(target, login: ShareLogin(user: "alice", password: "pw"), isKept: true)
        RunLoop.main.run(until: Date().addingTimeInterval(0.2))
        client.files = ["new.txt": Data()]
        sessions.pull()
        XCTAssertEqual(client.connects, 1)
        XCTAssertEqual(sessions.session?.view.items.map(\.name), ["new.txt"])
        XCTAssertNotNil(dialled)
    }

    func testAPullAfterTheConnectionEndedLogsInAgainAndForgetsALoginTheShareNowRejects() throws {
        let sessions = try XCTUnwrap(self.sessions)
        sessions.logIn(target, login: ShareLogin(user: "alice", password: "pw"), isKept: true)
        sessions.pull()
        XCTAssertEqual(client.connects, 2)
        XCTAssertEqual(sessions.heldLogins, [target.id])
        client.connectFailure = POSIXError(.ECONNREFUSED)
        sessions.pull()
        XCTAssertEqual(sessions.session?.view.error?.code, "share_login_rejected")
        XCTAssertTrue(sessions.heldLogins.isEmpty)
    }

    func testAReadShowsWhatItsForwardCarriedBelowItsSize() throws {
        let sessions = try XCTUnwrap(self.sessions)
        var dialled: LoopbackClient?
        client.onConnect = { port in dialled = LoopbackClient(port: port) }
        client.files = ["big.bin": Data(count: 100)]
        sessions.logIn(target, login: ShareLogin(user: "alice", password: "pw"), isKept: true)
        XCTAssertTrue(RunLoopWait.until { !self.transport.streams.isEmpty })
        let end = try XCTUnwrap(transport.streams.first?.end)
        let session = try XCTUnwrap(sessions.session)
        client.isHolding = true
        session.open(try XCTUnwrap(session.view.items.first))
        XCTAssertEqual(session.view.transfers["big.bin"]?.done, 50)

        end.write(Data(count: 70))
        RunLoop.main.run(until: Date().addingTimeInterval(0.6))
        XCTAssertEqual(session.view.transfers["big.bin"]?.done, 70)
        end.write(Data(count: 70))
        RunLoop.main.run(until: Date().addingTimeInterval(0.6))
        XCTAssertEqual(session.view.transfers["big.bin"]?.done, 99)

        client.finish()
        XCTAssertNil(session.view.transfers["big.bin"])
        XCTAssertEqual(session.view.preview?.lastPathComponent, "big.bin")
        XCTAssertNotNil(dialled)
    }

    func testTheForwardAcceptsNothingWhileTheHubHasNoChannel() throws {
        let sessions = try XCTUnwrap(self.sessions)
        var down = hub(services: [try XCTUnwrap(entry)])
        down.connection = .connecting
        down.connectedAddress = ""
        sessions.take([down])
        var dialled: LoopbackClient?
        client.onConnect = { port in dialled = LoopbackClient(port: port) }
        sessions.logIn(target, login: ShareLogin(user: "alice", password: "pw"), isKept: true)
        RunLoop.main.run(until: Date().addingTimeInterval(0.2))
        XCTAssertTrue(transport.streams.isEmpty)
        sessions.take([hub(services: [try XCTUnwrap(entry)])])
        XCTAssertTrue(RunLoopWait.until { self.transport.streams.count == 1 })
        XCTAssertNotNil(dialled)
    }

    func testAMachineShareLogsInWithTheHubsLogin() throws {
        let sessions = try XCTUnwrap(self.sessions)
        sessions.open(machine)
        XCTAssertEqual(client.connected?.login, ShareLogin(user: "smb_iffi", password: "generated"))  // scan: allow
        XCTAssertNotNil(sessions.session)
        XCTAssertTrue(sessions.heldLogins.isEmpty)
        XCTAssertNil(secrets.items[SharePage.loginsAccount])
        sessions.suspend()
        sessions.foreground()
        XCTAssertEqual(asked, 2)
        XCTAssertEqual(client.connected?.login, ShareLogin(user: "smb_iffi", password: "generated"))  // scan: allow
    }

    func testAMachinesShareRefusingTheHubsLoginReadsTheHubLoginCodeAndForgetsNothing() throws {
        let sessions = try XCTUnwrap(self.sessions)
        client.connectFailure = POSIXError(.ECONNREFUSED)
        sessions.open(machine)
        XCTAssertEqual(sessions.rows[machine.id]?.error?.code, "share_hub_login_rejected")
        XCTAssertTrue(sessions.heldLogins.isEmpty)
        XCTAssertNil(sessions.session)
    }

    func testAMachinesShareTheHubRefusesShowsTheHubsCode() throws {
        material = .failure(.refusal("permission_denied", ["kind": "file"]))
        let sessions = try XCTUnwrap(self.sessions)
        sessions.open(machine)
        XCTAssertEqual(sessions.rows[machine.id]?.error?.code, "permission_denied")
        XCTAssertNil(client.connected)
    }

    func testADeclaredShareWithNoLoginHeldOpensNothing() throws {
        let sessions = try XCTUnwrap(self.sessions)
        sessions.open(target)
        XCTAssertNil(client.connected)
        XCTAssertEqual(asked, 0)
    }
}

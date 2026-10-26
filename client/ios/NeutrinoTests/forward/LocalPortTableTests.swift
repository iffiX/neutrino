import XCTest

@testable import Neutrino

final class LocalPortTableTests: XCTestCase {
    private var defaults = UserDefaults()
    private var suite = ""
    private var busy: Set<String> = []

    private let hubNumbers: [String: (port: Int, protocol: String)] = [
        "b1/gitea_d1_web": (27311, "tcp"), "b1/gitea_d1_ssh": (30418, "tcp"),
    ]

    override func setUp() {
        suite = "neutrino.tests.\(UUID().uuidString)"
        defaults = UserDefaults(suiteName: suite) ?? .standard
        busy = []
    }

    override func tearDown() {
        defaults.removePersistentDomain(forName: suite)
    }

    private func table() -> LocalPortTable {
        LocalPortTable(defaults: defaults, isFree: { port, kind, _ in !self.busy.contains("\(port)/\(kind)") })
    }

    func testAnAppEntryListensOnTheHubsNumberUntilThePersonSetsOne() throws {
        let table = self.table()
        XCTAssertEqual(try table.port(forEntry: "b1/gitea_d1_web", hubPort: 27311, protocol: "tcp"), 27311)
        try table.configure("b1/gitea_d1_web", number: 28080, protocol: "tcp", hubNumbers: hubNumbers)
        XCTAssertEqual(self.table().number(of: "b1/gitea_d1_web"), 28080)
        XCTAssertEqual(try table.port(forEntry: "b1/gitea_d1_web", hubPort: 27311, protocol: "tcp"), 28080)
        try table.configure("b1/gitea_d1_web", number: nil, protocol: "tcp", hubNumbers: hubNumbers)
        XCTAssertEqual(table.port(of: "b1/gitea_d1_web", hubPort: 27311), 27311)
    }

    func testANumberAnotherEntryHoldsIsRefusedUnlessItsProtocolDiffers() throws {
        let table = self.table()
        XCTAssertThrowsError(
            try table.configure("b1/gitea_d1_web", number: 30418, protocol: "tcp", hubNumbers: hubNumbers)
        ) { error in XCTAssertEqual((error as? ClientError)?.code, "port_taken") }
        try table.configure("b1/a_port", number: 28080, protocol: "tcp", hubNumbers: hubNumbers)
        XCTAssertNoThrow(try table.configure("b1/a_port_udp", number: 28080, protocol: "udp", hubNumbers: hubNumbers))
        XCTAssertThrowsError(try table.configure("b1/x", number: 80, protocol: "tcp", hubNumbers: hubNumbers)) {
            error in XCTAssertEqual((error as? ClientError)?.code, "port_range")
        }
    }

    func testAHeldNumberIsRefusedAndNeverMoves() {
        busy = ["27311/tcp"]
        XCTAssertThrowsError(try table().port(forEntry: "b1/gitea_d1_web", hubPort: 27311, protocol: "tcp")) {
            error in XCTAssertEqual((error as? ClientError)?.code, "port_taken")
        }
        XCTAssertNil(table().number(of: "b1/gitea_d1_web"))
    }

    func testAForwardOfNoAppKeepsItsPick() throws {
        let table = self.table()
        XCTAssertEqual(try table.pick(for: "b1/#panel", protocol: "tcp"), 20000)
        busy = ["20001/tcp"]
        XCTAssertEqual(try table.pick(for: "b2/#panel", protocol: "tcp"), 20002)
        XCTAssertEqual(try self.table().pick(for: "b1/#panel", protocol: "tcp"), 20000)
        busy = ["20000/tcp"]
        XCTAssertEqual(try self.table().pick(for: "b1/#panel", protocol: "tcp"), 20001)
    }

    func testAKeptEntryWithNoProtocolReadsAsTcp() throws {
        defaults.set(Data(#"{"b1/p":{"is_fixed":true,"port":28080}}"#.utf8), forKey: Client.settingsKeyLocalPorts)
        XCTAssertEqual(table().all["b1/p"], LocalPortChoice(isFixed: true, port: 28080, protocol: "tcp"))
    }
}

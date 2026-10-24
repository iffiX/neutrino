import XCTest

@testable import Neutrino

final class BindingStoreTests: XCTestCase {
    func testBindingsAreKeptInTheKeychainItemAndReadBackByTheNextStore() throws {
        let secrets = FakeSecretStore()
        let store = BindingStore(secrets: secrets)
        let machineId = store.machineId
        try store.put(Samples.binding)
        try store.update("b1") { $0.hubName = "Renamed" }
        XCTAssertNotNil(secrets.read(account: Client.bindingsAccount))

        let again = BindingStore(secrets: secrets)
        XCTAssertEqual(again.bindings.map(\.hubName), ["Renamed"])
        XCTAssertEqual(again.machineId, machineId)
        XCTAssertEqual(machineId.count, 32)
    }

    func testAChangeIsTold() throws {
        let store = BindingStore(secrets: FakeSecretStore())
        var told: [[String]] = []
        store.onChange = { told.append($0.map(\.id)) }
        try store.put(Samples.binding)
        try store.update("b1") { _ in }
        try store.remove("b1")
        XCTAssertEqual(told, [["b1"], []])
    }

    func testOneBindingPerHubIdIsKeptTheOneJoinedLast() throws {
        let secrets = FakeSecretStore()
        let store = BindingStore(secrets: secrets)
        try store.put(Samples.binding)
        var pending = Samples.binding
        pending.id = "p1"
        pending.hubId = ""
        pending.ticket = "TICKET"
        try store.put(pending)
        var other = Samples.binding
        other.id = "b2"
        other.hubId = "hub-2"
        try store.put(other)
        var later = Samples.binding
        later.id = "b3"
        try store.put(later)
        XCTAssertEqual(try store.dropRepeatedHubs().map(\.id), ["b1"])
        XCTAssertEqual(BindingStore(secrets: secrets).bindings.map(\.id), ["p1", "b2", "b3"])
        XCTAssertEqual(try store.dropRepeatedHubs(), [])
    }

    func testAnItemThatDoesNotReadIsNoBinding() throws {
        let secrets = FakeSecretStore()
        try secrets.write(account: Client.bindingsAccount, data: Data("not json".utf8))
        XCTAssertTrue(BindingStore(secrets: secrets).bindings.isEmpty)
    }
}

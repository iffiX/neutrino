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

    func testAnItemThatDoesNotReadIsNoBinding() throws {
        let secrets = FakeSecretStore()
        try secrets.write(account: Client.bindingsAccount, data: Data("not json".utf8))
        XCTAssertTrue(BindingStore(secrets: secrets).bindings.isEmpty)
    }
}

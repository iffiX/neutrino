import XCTest

@testable import Neutrino

final class ShareLoginStoreTests: XCTestCase {
    private let alice = ShareLogin(user: "alice", password: "pw")

    func testAKeptLoginIsReadBackFromTheKeychain() throws {
        let secrets = FakeSecretStore()
        try ShareLoginStore(secrets: secrets).put("b1/music", alice, isKept: true)
        let again = ShareLoginStore(secrets: secrets)
        XCTAssertEqual(again.login("b1/music"), alice)
        XCTAssertTrue(again.isKept("b1/music"))
    }

    func testALoginForThisRunIsNeverWrittenAndReplacesAKeptOne() throws {
        let secrets = FakeSecretStore()
        let store = ShareLoginStore(secrets: secrets)
        try store.put("b1/music", alice, isKept: true)
        try store.put("b1/music", ShareLogin(user: "bob", password: "pw"), isKept: false)
        XCTAssertEqual(store.login("b1/music")?.user, "bob")
        XCTAssertFalse(store.isKept("b1/music"))
        XCTAssertNil(secrets.items[SharePage.loginsAccount])
        XCTAssertNil(ShareLoginStore(secrets: secrets).login("b1/music"))
    }

    func testLeavingAHubForgetsTheLoginsOfItsSharesAlone() throws {
        let secrets = FakeSecretStore()
        let store = ShareLoginStore(secrets: secrets)
        try store.put("b1/music", alice, isKept: true)
        try store.put("b2/photos", alice, isKept: true)
        try store.forget(bindingId: "b1")
        XCTAssertEqual(store.keys, ["b2/photos"])
        XCTAssertEqual(ShareLoginStore(secrets: secrets).keys, ["b2/photos"])
    }

    func testAnItemThatDoesNotReadHoldsNoLogin() throws {
        let secrets = FakeSecretStore()
        try secrets.write(account: SharePage.loginsAccount, data: Data("not json".utf8))
        XCTAssertTrue(ShareLoginStore(secrets: secrets).keys.isEmpty)
    }
}

import UniformTypeIdentifiers
import XCTest

@testable import Neutrino

final class SharePhotoDeliveryTests: XCTestCase {
    private var place = FileManager.default.temporaryDirectory

    override func setUpWithError() throws {
        place = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: place, withIntermediateDirectories: true)
    }

    override func tearDown() {
        try? FileManager.default.removeItem(at: place)
    }

    private func delivered(_ provider: NSItemProvider) throws -> Result<URL, Error> {
        let done = expectation(description: "delivered")
        var delivered: Result<URL, Error>?
        SharePhotoDelivery(provider: provider).deliver(into: place) { result in
            delivered = result
            done.fulfill()
        }
        wait(for: [done], timeout: 10)
        return try XCTUnwrap(delivered)
    }

    func testThePickedFileIsCopiedOutUnderTheSuggestedNameWithItsExtension() throws {
        let original = place.appendingPathComponent("picker").appendingPathComponent("4F2A.heic")
        try FileManager.default.createDirectory(
            at: original.deletingLastPathComponent(), withIntermediateDirectories: true)
        try Data("heic bytes".utf8).write(to: original)
        let provider = NSItemProvider()
        provider.registerFileRepresentation(
            forTypeIdentifier: UTType.heic.identifier, fileOptions: [], visibility: .all
        ) { load in
            load(original, false, nil)
            return nil
        }
        provider.suggestedName = "IMG_0042"
        let file = try delivered(provider).get()
        XCTAssertEqual(file.lastPathComponent, "IMG_0042.heic")
        XCTAssertEqual(file.deletingLastPathComponent().standardizedFileURL, place.standardizedFileURL)
        XCTAssertEqual(try Data(contentsOf: file), Data("heic bytes".utf8))
    }

    func testAnItemWithNoPhotoOrVideoIsNotHandedOver() throws {
        let provider = NSItemProvider(item: "notes" as NSString, typeIdentifier: UTType.plainText.identifier)
        XCTAssertThrowsError(try delivered(provider).get())
    }
}

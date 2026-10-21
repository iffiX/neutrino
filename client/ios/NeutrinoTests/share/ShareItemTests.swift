import XCTest

@testable import Neutrino

final class ShareItemTests: XCTestCase {
    private func item(_ name: String, isFolder: Bool = false) -> ShareItem {
        ShareItem(name: name, isFolder: isFolder, size: 0, modified: nil)
    }

    func testFoldersComeFirstThenFilesEachByNameWithNumbersByValue() {
        let ordered = ShareItem.ordered([
            item("track10.mp3"), item("Zebra", isFolder: true), item("track2.mp3"), item("apple", isFolder: true),
            item("Track1.mp3"),
        ])
        XCTAssertEqual(ordered.map(\.name), ["apple", "Zebra", "Track1.mp3", "track2.mp3", "track10.mp3"])
    }
}

import XCTest

@testable import Neutrino

final class ShareNameTests: XCTestCase {
    func testAFileIsNumberedBeforeItsExtensionAndAFolderAtItsEnd() {
        XCTAssertEqual(ShareName.numbered("report.pdf", isFolder: false, attempt: 0), "report.pdf")
        XCTAssertEqual(ShareName.numbered("report.pdf", isFolder: false, attempt: 2), "report (2).pdf")
        XCTAssertEqual(ShareName.numbered("backup.tar.gz", isFolder: false, attempt: 1), "backup.tar (1).gz")
        XCTAssertEqual(ShareName.numbered("README", isFolder: false, attempt: 1), "README (1)")
        XCTAssertEqual(ShareName.numbered(".bashrc", isFolder: false, attempt: 1), ".bashrc (1)")
        XCTAssertEqual(ShareName.numbered("v1.2", isFolder: true, attempt: 3), "v1.2 (3)")
    }

    func testAnItemFromPhotosTakesTheSuggestedNameWithTheExtensionOfItsFile() {
        let heic = URL(fileURLWithPath: "/tmp/picker/4F2A.heic")
        XCTAssertEqual(ShareName.photo(suggested: "IMG_0042", received: heic), "IMG_0042.heic")
        XCTAssertEqual(ShareName.photo(suggested: "IMG_0042.HEIC", received: heic), "IMG_0042.HEIC")
        XCTAssertEqual(ShareName.photo(suggested: nil, received: heic), "4F2A.heic")
        XCTAssertEqual(ShareName.photo(suggested: "", received: heic), "4F2A.heic")
        let bare = URL(fileURLWithPath: "/tmp/picker/clip")
        XCTAssertEqual(ShareName.photo(suggested: "IMG_0043", received: bare), "IMG_0043")
    }

    func testANameIsValidWithoutTheCharactersAShareForbids() {
        XCTAssertTrue(ShareName.isValid("photos 2026"))
        XCTAssertTrue(ShareName.isValid("照片.jpg"))
        XCTAssertFalse(ShareName.isValid(""))
        XCTAssertFalse(ShareName.isValid("  "))
        XCTAssertFalse(ShareName.isValid(" padded"))
        XCTAssertFalse(ShareName.isValid("."))
        XCTAssertFalse(ShareName.isValid(".."))
        XCTAssertFalse(ShareName.isValid("a/b"))
        XCTAssertFalse(ShareName.isValid("a\\b"))
        XCTAssertFalse(ShareName.isValid("what?"))
        XCTAssertFalse(ShareName.isValid("tab\there"))
    }
}

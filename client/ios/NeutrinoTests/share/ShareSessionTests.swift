import XCTest

@testable import Neutrino

final class ShareSessionTests: XCTestCase {
    private var client = FakeShareClient()
    private var directory = FileManager.default.temporaryDirectory
    private var session: ShareSession?

    override func setUp() {
        client = FakeShareClient()
        directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        let session = ShareSession(
            target: ShareTarget(bindingId: "b1", entryId: "music", title: "music", share: "music", users: []),
            login: ShareLogin(user: "alice", password: "pw"), makeClient: { self.client },
            openConnect: { .failure(.refusal(Channel.codeHubUnreachable)) }, directory: directory)
        self.session = session
    }

    override func tearDown() {
        session?.close()
        RunLoop.main.run(until: Date().addingTimeInterval(0.1))
        try? FileManager.default.removeItem(at: directory)
    }

    private func started() throws -> ShareSession {
        let session = try XCTUnwrap(self.session)
        var refusal: ClientError?
        session.start { refusal = $0 }
        XCTAssertNil(refusal)
        session.reload()
        return session
    }

    private func picked(_ name: String, _ text: String) throws -> URL {
        let place = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: place, withIntermediateDirectories: true)
        let url = place.appendingPathComponent(name)
        try Data(text.utf8).write(to: url)
        return url
    }

    private func settle(_ condition: () -> Bool) {
        let end = Date().addingTimeInterval(5)
        while !condition() && Date() < end {
            RunLoop.main.run(until: Date().addingTimeInterval(0.02))
        }
    }

    func testTheFolderListsFoldersFirstThenFilesEachByName() throws {
        client.folders = ["b", "A"]
        client.files = ["z.txt": Data(), "a10.txt": Data(), "a2.txt": Data()]
        let session = try started()
        XCTAssertEqual(session.view.items.map(\.name), ["A", "b", "a2.txt", "a10.txt", "z.txt"])
        XCTAssertEqual(session.view.items.map(\.isFolder), [true, true, false, false, false])
    }

    func testAFolderOpensAndTheBackArrowGoesUpThenClosesAtTheRoot() throws {
        client.folders = ["docs"]
        client.files = ["docs/plan.md": Data("x".utf8)]
        let session = try started()
        session.enter(try XCTUnwrap(session.view.items.first))
        XCTAssertEqual(session.view.path, SharePath(["docs"]))
        XCTAssertEqual(session.view.items.map(\.name), ["plan.md"])
        XCTAssertTrue(session.back())
        XCTAssertEqual(session.view.items.map(\.name), ["docs"])
        XCTAssertFalse(session.back())
    }

    func testATappedFileIsReadAndShownInThePreview() throws {
        client.files = ["song.mp3": Data("la la".utf8)]
        let session = try started()
        session.open(try XCTUnwrap(session.view.items.first))
        let preview = try XCTUnwrap(session.view.preview)
        XCTAssertEqual(preview.lastPathComponent, "song.mp3")
        XCTAssertEqual(try Data(contentsOf: preview), Data("la la".utf8))
        session.closePreview()
        XCTAssertFalse(FileManager.default.fileExists(atPath: preview.path))
    }

    func testSaveToFilesReadsTheFileForTheExportPicker() throws {
        client.files = ["song.mp3": Data("la la".utf8)]
        let session = try started()
        session.save(try XCTUnwrap(session.view.items.first))
        XCTAssertEqual(session.view.export?.lastPathComponent, "song.mp3")
        XCTAssertNil(session.view.preview)
    }

    func testACancelledReadLeavesNoFile() throws {
        client.files = ["song.mp3": Data("la la".utf8)]
        let session = try started()
        client.isHolding = true
        session.open(try XCTUnwrap(session.view.items.first))
        XCTAssertEqual(session.view.transfers["song.mp3"]?.done, 2)
        session.cancel("song.mp3")
        XCTAssertNil(session.view.transfers["song.mp3"])
        client.finish()
        XCTAssertNil(session.view.preview)
        let left = FileManager.default.enumerator(atPath: directory.path)?.allObjects as? [String] ?? []
        XCTAssertFalse(left.contains { $0.hasSuffix("song.mp3") })
    }

    func testAnUploadTakesTheFirstFreeNumberedName() throws {
        client.files = ["report.pdf": Data(), "report (1).pdf": Data()]
        let session = try started()
        session.upload([try picked("report.pdf", "new")])
        settle { client.files["report (2).pdf"] == Data("new".utf8) }
        XCTAssertEqual(client.files["report (2).pdf"], Data("new".utf8))
        XCTAssertEqual(client.files["report.pdf"], Data())
        XCTAssertTrue(session.view.transfers.isEmpty)
        XCTAssertTrue(session.view.items.contains { $0.name == "report (2).pdf" })
    }

    func testACancelledWriteDeletesThePartItWrote() throws {
        let session = try started()
        client.isHolding = true
        session.upload([try picked("notes.txt", "hello")])
        settle { session.view.transfers["notes.txt"]?.done == 2 }
        session.cancel("notes.txt")
        client.finish()
        XCTAssertNil(client.files["notes.txt"])
        XCTAssertEqual(client.removed, ["notes.txt"])
        XCTAssertTrue(session.view.transfers.isEmpty)
    }

    func testANewFolderTakesTheFirstFreeNumberedName() throws {
        client.folders = ["photos"]
        let session = try started()
        session.makeFolder("photos")
        XCTAssertTrue(client.folders.contains("photos (1)"))
        XCTAssertFalse(session.view.isMakingFolder)
        XCTAssertEqual(session.view.items.map(\.name), ["photos", "photos (1)"])
    }

    func testARenameToANameTheFolderHoldsIsRefused() throws {
        client.files = ["a.txt": Data(), "b.txt": Data()]
        let session = try started()
        let item = try XCTUnwrap(session.view.items.first)
        session.rename(item, to: "b.txt")
        XCTAssertEqual(session.view.errors["a.txt"]?.code, "share_name_taken")
        session.rename(item, to: "c.txt")
        XCTAssertNil(session.view.errors["a.txt"])
        XCTAssertEqual(session.view.items.map(\.name), ["b.txt", "c.txt"])
    }

    func testDeleteRemovesAFolderWithEverythingInIt() throws {
        client.folders = ["old", "old/deep"]
        client.files = ["old/deep/x.txt": Data(), "keep.txt": Data()]
        let session = try started()
        session.delete(try XCTUnwrap(session.view.items.first))
        XCTAssertEqual(client.folders, [])
        XCTAssertEqual(Set(client.files.keys), ["keep.txt"])
        XCTAssertEqual(session.view.items.map(\.name), ["keep.txt"])
    }

    func testATransferTheBackgroundCutShowsInterruptedAndItsRetryWritesTheSameNameAgain() throws {
        let session = try started()
        client.isHolding = true
        session.upload([try picked("clip.mov", "frames")])
        settle { session.view.transfers["clip.mov"]?.done == 3 }

        session.suspend()
        XCTAssertTrue(client.isDisconnected)
        client.finish(POSIXError(.ENOTCONN))
        XCTAssertEqual(session.view.transfers["clip.mov"]?.error?.code, "share_interrupted")
        XCTAssertEqual(client.files["clip.mov"], Data())

        var refusal: ClientError?
        session.resume { refusal = $0 }
        XCTAssertNil(refusal)
        client.isHolding = false
        session.retry("clip.mov")
        XCTAssertEqual(client.removed, ["clip.mov"])
        XCTAssertEqual(client.files["clip.mov"], Data("frames".utf8))
        XCTAssertTrue(session.view.transfers.isEmpty)
    }

    func testAReadTheBackgroundCutShowsInterruptedAndItsRetryReadsAgain() throws {
        client.files = ["song.mp3": Data("la la".utf8)]
        let session = try started()
        client.isHolding = true
        session.open(try XCTUnwrap(session.view.items.first))
        session.suspend()
        client.finish(POSIXError(.ENOTCONN))
        XCTAssertEqual(session.view.transfers["song.mp3"]?.error?.code, "share_interrupted")
        session.resume { _ in }
        client.isHolding = false
        session.retry("song.mp3")
        XCTAssertEqual(session.view.preview?.lastPathComponent, "song.mp3")
    }

    func testTransfersRunOneAtATimeInTheOrderTheyWereAdded() throws {
        client.files = ["a.txt": Data("aa".utf8), "b.txt": Data("bb".utf8), "c.txt": Data("cc".utf8)]
        let session = try started()
        client.isHolding = true
        for item in session.view.items { session.open(item) }
        XCTAssertEqual(client.started, ["a.txt"])
        XCTAssertEqual(session.view.transfers["a.txt"]?.isWaiting, false)
        XCTAssertEqual(session.view.transfers["b.txt"]?.isWaiting, true)
        XCTAssertEqual(session.view.transfers["c.txt"]?.isWaiting, true)

        client.finish()
        XCTAssertEqual(session.view.preview?.lastPathComponent, "a.txt")
        XCTAssertEqual(client.started, ["a.txt", "b.txt"])
        XCTAssertEqual(session.view.transfers["b.txt"]?.isWaiting, false)
        XCTAssertEqual(session.view.transfers["c.txt"]?.isWaiting, true)
        client.finish()
        XCTAssertEqual(client.started, ["a.txt", "b.txt", "c.txt"])
    }

    func testAnUploadWaitsForTheReadAddedBeforeIt() throws {
        client.files = ["song.mp3": Data("la la".utf8)]
        let session = try started()
        client.isHolding = true
        session.open(try XCTUnwrap(session.view.items.first))
        session.upload([try picked("notes.txt", "hello")])
        settle { session.view.transfers["notes.txt"]?.total == 5 }
        XCTAssertEqual(session.view.transfers["notes.txt"]?.isWaiting, true)
        XCTAssertEqual(client.started, ["song.mp3"])
        client.isHolding = false
        client.finish()
        XCTAssertEqual(client.started, ["song.mp3", "notes.txt"])
        XCTAssertEqual(client.files["notes.txt"], Data("hello".utf8))
    }

    func testCancelOnAWaitingRowRemovesItAtOnceAndItNeverStarts() throws {
        client.files = ["a.txt": Data("aa".utf8), "b.txt": Data("bb".utf8)]
        let session = try started()
        client.isHolding = true
        for item in session.view.items { session.open(item) }
        session.cancel("b.txt")
        XCTAssertNil(session.view.transfers["b.txt"])
        client.finish()
        XCTAssertEqual(client.started, ["a.txt"])
        XCTAssertTrue(session.view.transfers.isEmpty)
    }

    func testTheBackgroundEndCutsTheWaitingTransfersAsWellAsTheRunningOne() throws {
        client.files = ["a.txt": Data("aa".utf8), "b.txt": Data("bb".utf8)]
        let session = try started()
        client.isHolding = true
        for item in session.view.items { session.open(item) }
        session.suspend()
        client.finish(POSIXError(.ENOTCONN))
        for key in ["a.txt", "b.txt"] {
            XCTAssertEqual(session.view.transfers[key]?.error?.code, "share_interrupted")
            XCTAssertEqual(session.view.transfers[key]?.isWaiting, false)
        }
        session.resume { _ in }
        client.isHolding = false
        session.retry("b.txt")
        XCTAssertEqual(client.started, ["a.txt", "b.txt"])
        XCTAssertEqual(session.view.preview?.lastPathComponent, "b.txt")
    }

    func testItemsFromPhotosAreWrittenAsUploadsAndOneNotHandedOverIsWordedOnThePageLine() throws {
        client.files = ["IMG_0001.heic": Data()]
        let session = try started()
        session.upload(deliveries: [
            FakeShareDelivery(name: "IMG_0001.heic", text: "photo"),
            FakeShareDelivery(name: "IMG_0002.mov", text: nil),
            FakeShareDelivery(name: "IMG_0003.mov", text: "video"),
        ])
        settle { client.files["IMG_0001 (1).heic"] != nil && client.files["IMG_0003.mov"] == Data("video".utf8) }
        XCTAssertEqual(client.files["IMG_0001 (1).heic"], Data("photo".utf8))
        XCTAssertEqual(client.files["IMG_0001.heic"], Data())
        XCTAssertNil(client.files["IMG_0002.mov"])
        XCTAssertEqual(session.view.error?.code, "share_photo_unavailable")
        XCTAssertTrue(session.view.transfers.isEmpty)
        XCTAssertEqual(Set(session.view.items.map(\.name)), ["IMG_0001 (1).heic", "IMG_0001.heic", "IMG_0003.mov"])
    }

    func testAnItemFromPhotosIsCancelledAndRetriedAsAnUploadFromFilesIs() throws {
        let session = try started()
        client.isHolding = true
        session.upload(deliveries: [FakeShareDelivery(name: "IMG_0004.mov", text: "frames")])
        settle { session.view.transfers["IMG_0004.mov"]?.done == 3 }
        session.suspend()
        client.finish(POSIXError(.ENOTCONN))
        XCTAssertEqual(session.view.transfers["IMG_0004.mov"]?.error?.code, "share_interrupted")
        session.resume { _ in }
        client.isHolding = false
        session.retry("IMG_0004.mov")
        XCTAssertEqual(client.files["IMG_0004.mov"], Data("frames".utf8))
        XCTAssertTrue(session.view.transfers.isEmpty)
    }

    func testAFolderTheShareLacksIsWordedOnThePageLine() throws {
        let session = try started()
        session.enter(ShareItem(name: "gone", isFolder: true, size: 0, modified: nil))
        XCTAssertEqual(session.view.error?.code, "share_not_found")
    }
}

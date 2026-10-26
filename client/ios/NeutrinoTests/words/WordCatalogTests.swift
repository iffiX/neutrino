import XCTest

@testable import Neutrino

final class WordCatalogTests: XCTestCase {
    private let bundle = Bundle(for: ClientCore.self)

    /// The codes this app words besides the hub's: the link's, the transport's, the forwards' and the share page's.
    private let appCodes = [
        "link_missing", "link_unreadable", "link_incomplete", "link_not_for_client", "hub_untrusted",
        "hub_unreachable", "hub_refused", "client_internal", "enroll_no_token", "port_taken", "forward_failed",
        "web_token_missing", "unknown_request", "disconnect_first", "share_login_rejected", "share_access_denied",
        "share_not_found", "share_unreachable", "share_name_taken", "share_interrupted", "share_photo_unavailable",
        "rdp_core_missing", "rdp_login_failed", "rdp_closed", "rdp_launch_failed", "transport_missing",
        "transport_failed",
    ]

    func testEveryCodeIsWordedInBothLanguages() {
        for language in Client.languages {
            let words = WordCatalog.load(language: language, bundle: bundle)
            for code in Channel.hubCodes + appCodes {
                XCTAssertTrue(words.has("code.\(code)"), "\(language) words no code.\(code)")
            }
        }
    }

    func testEveryWayInIsWordedInBothLanguages() {
        for language in Client.languages {
            let words = WordCatalog.load(language: language, bundle: bundle)
            for way in Channel.reachedThrough {
                XCTAssertTrue(words.has("ui.through.\(way)"), "\(language) words no ui.through.\(way)")
            }
        }
    }

    func testEveryPageOfTheBarIsWordedInBothLanguages() {
        for language in Client.languages {
            let words = WordCatalog.load(language: language, bundle: bundle)
            for screen in AppScreen.tabs {
                XCTAssertTrue(words.has(screen.barKey), "\(language) words no \(screen.barKey)")
                XCTAssertTrue(words.has(screen.titleKey), "\(language) words no \(screen.titleKey)")
            }
        }
    }

    func testTheAppsCatalogAndTheDesktopsHoldNoKeyInCommon() throws {
        for language in Client.languages {
            let desktop = try XCTUnwrap(
                bundle.url(forResource: language, withExtension: "json", subdirectory: "locales"))
            let app = try XCTUnwrap(
                bundle.url(forResource: language, withExtension: "json", subdirectory: "app_locales"))
            let shared = Set(WordCatalog.flatten(try Data(contentsOf: desktop)).keys)
                .intersection(WordCatalog.flatten(try Data(contentsOf: app)).keys)
            XCTAssertEqual(shared, [], language)
        }
    }

    func testNestedAndDottedKeysReadAlikeAndParametersFillIn() {
        let words = WordCatalog(
            words: WordCatalog.flatten(Data(#"{"ui":{"a":"A {n}"},"code.x":"X {why}"}"#.utf8)))
        XCTAssertEqual(words.word("ui.a", ["n": "1"]), "A 1")
        XCTAssertEqual(words.refusal(.refusal("x", ["why": "because"])), "X because")
        XCTAssertEqual(words.refusal(.refusal("y")), "y")
        XCTAssertEqual(words.word("ui.missing"), "ui.missing")
    }
}

import SwiftTerm
import UIKit

/// What one tab's terminal view tells the app: its size, which opens or resizes the shell, and what the person
/// typed, with the key row's held modifiers spent on it.
final class TerminalViewBridge: NSObject, TerminalViewDelegate {
    /// The tab.
    let sessionId: String

    /// The row above the keyboard.
    let keyRow: TerminalKeyRow

    private weak var tabs: TerminalTabs?

    /// Join a tab's view to its tab.
    ///
    /// - Parameters:
    ///   - sessionId: The tab.
    ///   - tabs: The tabs.
    ///   - keyRow: The view's key row.
    init(sessionId: String, tabs: TerminalTabs, keyRow: TerminalKeyRow) {
        self.sessionId = sessionId
        self.tabs = tabs
        self.keyRow = keyRow
    }

    func sizeChanged(source: TerminalView, newCols: Int, newRows: Int) {
        tabs?.sized(sessionId, cols: newCols, rows: newRows)
    }

    func setTerminalTitle(source: TerminalView, title: String) {}

    func hostCurrentDirectoryUpdate(source: TerminalView, directory: String?) {}

    func send(source: TerminalView, data: ArraySlice<UInt8>) {
        tabs?.input(sessionId, keyRow.spend().applied(to: Data(data)))
    }

    func scrolled(source: TerminalView, position: Double) {}

    func requestOpenLink(source: TerminalView, link: String, params: [String: String]) {}

    func bell(source: TerminalView) {}

    func clipboardCopy(source: TerminalView, content: Data) {
        UIPasteboard.general.string = String(decoding: content, as: UTF8.self)
    }

    func clipboardRead(source: TerminalView) -> Data? {
        nil
    }

    func iTermContent(source: TerminalView, content: ArraySlice<UInt8>) {}

    func rangeChanged(source: TerminalView, startY: Int, endY: Int) {}

    /// Send a key of the row with the modifiers held when it was pressed.
    ///
    /// - Parameters:
    ///   - key: The key.
    ///   - modifiers: The modifiers.
    ///   - view: The tab's view, whose cursor mode an arrow follows.
    func press(_ key: TerminalKey, modifiers: TerminalModifiers, on view: TerminalView) {
        let isApplicationCursor = view.getTerminal().applicationCursor
        tabs?.input(sessionId, key.sequence(modifiers, isApplicationCursor: isApplicationCursor))
    }
}

import SwiftTerm
import UIKit

/// What one tab's terminal view tells the app: its size, which opens or resizes the shell, and what the person
/// typed, with the key row's held modifiers spent on it. A size the view takes while the keyboard slides waits for
/// the slide's end.
final class TerminalViewBridge: NSObject, TerminalViewDelegate {
    /// The tab.
    let sessionId: String

    /// The key row's held modifiers.
    let keys: TerminalKeyState

    private weak var tabs: TerminalTabs?
    private let keyboard: KeyboardMotion
    private var sent: (cols: Int, rows: Int)?

    /// Join a tab's view to its tab.
    ///
    /// - Parameters:
    ///   - sessionId: The tab.
    ///   - tabs: The tabs.
    ///   - keys: The key row's held modifiers.
    ///   - keyboard: The keyboard's slide.
    init(sessionId: String, tabs: TerminalTabs, keys: TerminalKeyState, keyboard: KeyboardMotion) {
        self.sessionId = sessionId
        self.tabs = tabs
        self.keys = keys
        self.keyboard = keyboard
    }

    func sizeChanged(source: TerminalView, newCols: Int, newRows: Int) {
        guard !keyboard.isMoving else { return }
        send(cols: newCols, rows: newRows)
    }

    /// Tell the tab the size its view has, when the tab was last told another.
    ///
    /// - Parameter view: The tab's view.
    func sendSize(of view: TerminalView) {
        let terminal = view.getTerminal()
        guard sent?.cols != terminal.cols || sent?.rows != terminal.rows else { return }
        send(cols: terminal.cols, rows: terminal.rows)
    }

    func setTerminalTitle(source: TerminalView, title: String) {}

    func hostCurrentDirectoryUpdate(source: TerminalView, directory: String?) {}

    func send(source: TerminalView, data: ArraySlice<UInt8>) {
        tabs?.input(sessionId, keys.spend().applied(to: Data(data)))
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

    private func send(cols: Int, rows: Int) {
        sent = (cols, rows)
        tabs?.sized(sessionId, cols: cols, rows: rows)
    }
}

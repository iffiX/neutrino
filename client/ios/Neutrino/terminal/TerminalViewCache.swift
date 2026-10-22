import SwiftTerm
import UIKit

/// One terminal view per tab, kept while the tab lives so switching tabs loses no output; each view is fed its
/// tab's kept output when made and every byte after, and is drawn in the colours of the palette in force. A tap on
/// a view opens the keyboard.
final class TerminalViewCache {
    /// The key row, one for every tab.
    let keys = TerminalKeyState()

    /// The keyboard as the terminals follow it.
    let focus = TerminalKeyboardFocus()

    private let tabs: TerminalTabs
    private var views: [String: TerminalView] = [:]
    private var bridges: [String: TerminalViewBridge] = [:]
    private var colors = TerminalColors(palette: .dark)

    /// Keep the views of every tab.
    ///
    /// - Parameter tabs: The tabs.
    init(tabs: TerminalTabs) {
        self.tabs = tabs
        tabs.onOutput = { [weak self] sessionId, data in
            self?.views[sessionId]?.feed(byteArray: ArraySlice([UInt8](data)))
        }
        tabs.onReplay = { [weak self] sessionId in
            self?.views[sessionId]?.getTerminal().resetToInitialState()
        }
    }

    /// Draw every view in a palette.
    ///
    /// - Parameter palette: The palette.
    func paint(_ palette: NeutrinoPalette) {
        colors = TerminalColors(palette: palette)
        for view in views.values { colors.paint(view) }
    }

    /// The view of one tab, made with its kept output when it has none.
    ///
    /// - Parameter sessionId: The tab.
    /// - Returns: The view.
    func view(of sessionId: String) -> TerminalView {
        if let view = views[sessionId] { return view }
        let view = TerminalView(
            frame: CGRect(x: 0, y: 0, width: 320, height: 240),
            font: UIFont.monospacedSystemFont(ofSize: TerminalPage.fontSize, weight: .regular))
        let bridge = TerminalViewBridge(sessionId: sessionId, tabs: tabs, keys: keys)
        view.inputAccessoryView = nil
        view.terminalDelegate = bridge
        view.optionAsMetaKey = false
        focus.watch(view)
        colors.paint(view)
        let kept = tabs.keptOutput(sessionId)
        if !kept.isEmpty { view.feed(byteArray: ArraySlice([UInt8](kept))) }
        views[sessionId] = view
        bridges[sessionId] = bridge
        return view
    }

    /// Open the keyboard on one tab's terminal, as the status line's Keyboard does; a terminal that has the focus
    /// with no keyboard shown takes it again.
    ///
    /// - Parameter sessionId: The tab shown.
    func openKeyboard(on sessionId: String) {
        guard let view = views[sessionId] else { return }
        if view.isFirstResponder { _ = view.resignFirstResponder() }
        _ = view.becomeFirstResponder()
    }

    /// Send a key of the key row to one tab, with the modifiers held; a modifier is held or let go instead.
    ///
    /// - Parameters:
    ///   - key: The key.
    ///   - sessionId: The tab shown.
    func press(_ key: TerminalKey, on sessionId: String) {
        if key.isModifier {
            keys.toggle(key)
            return
        }
        let modifiers = keys.spend()
        guard let view = views[sessionId], let bridge = bridges[sessionId] else { return }
        bridge.press(key, modifiers: modifiers, on: view)
    }

    /// Tell the tab the size its view has now, which opens its shell when it has none.
    ///
    /// - Parameter sessionId: The tab.
    func reportSize(of sessionId: String) {
        guard let terminal = views[sessionId]?.getTerminal() else { return }
        tabs.sized(sessionId, cols: terminal.cols, rows: terminal.rows)
    }

    /// Forget the views of tabs that are gone.
    ///
    /// - Parameter sessionIds: The tabs that remain.
    func keep(_ sessionIds: Set<String>) {
        for sessionId in views.keys where !sessionIds.contains(sessionId) {
            views[sessionId]?.removeFromSuperview()
            views[sessionId] = nil
            bridges[sessionId] = nil
        }
    }
}

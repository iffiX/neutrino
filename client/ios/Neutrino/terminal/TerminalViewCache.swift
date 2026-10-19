import SwiftTerm
import UIKit

/// One terminal view per tab, kept while the tab lives so switching tabs loses no output; each view is fed its
/// tab's kept output when made and every byte after.
final class TerminalViewCache {
    private let tabs: TerminalTabs
    private var views: [String: TerminalView] = [:]
    private var bridges: [String: TerminalViewBridge] = [:]
    private var palette = NeutrinoPalette.dark
    private var accent = UIColor(NeutrinoPalette.dark.accent)

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
        self.palette = palette
        accent = UIColor(palette.accent)
        for view in views.values { style(view) }
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
        let keyRow = TerminalKeyRow(accent: accent)
        let bridge = TerminalViewBridge(sessionId: sessionId, tabs: tabs, keyRow: keyRow)
        keyRow.onKey = { [weak bridge, weak view] key, modifiers in
            guard let bridge, let view else { return }
            bridge.press(key, modifiers: modifiers, on: view)
        }
        view.inputAccessoryView = keyRow
        view.terminalDelegate = bridge
        view.optionAsMetaKey = false
        style(view)
        let kept = tabs.keptOutput(sessionId)
        if !kept.isEmpty { view.feed(byteArray: ArraySlice([UInt8](kept))) }
        views[sessionId] = view
        bridges[sessionId] = bridge
        return view
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

    private func style(_ view: TerminalView) {
        view.nativeBackgroundColor = UIColor(palette.termBg)
        view.nativeForegroundColor = UIColor(palette.termFg)
    }
}

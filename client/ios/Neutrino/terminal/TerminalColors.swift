import SwiftTerm
import UIKit

/// The colours a terminal draws in under one palette: the sixteen ANSI colours, the same under every palette, and
/// the default background, text, cursor and selection, taken from the palette. The 256-colour cube and grey ramp
/// are xterm's.
struct TerminalColors {
    /// The sixteen ANSI colours, black to bright white, as `0xRRGGBB`.
    let ansi: [UInt32]

    /// The background of a cell with no colour of its own: the page's background.
    let background: UIColor

    /// The text with no colour of its own: the page's text.
    let foreground: UIColor

    /// The cursor: the accent.
    let cursor: UIColor

    /// The selection: the accent at `TerminalPage.selectionOpacity`.
    let selection: UIColor

    /// The scroll bar, dark on a light background and light on a dark one.
    let indicator: UIScrollView.IndicatorStyle

    /// The colours under a palette.
    ///
    /// - Parameter palette: The palette of the theme in force.
    init(palette: NeutrinoPalette) {
        ansi = TerminalPage.ansiColors
        background = UIColor(palette.bg)
        foreground = UIColor(palette.text)
        cursor = UIColor(palette.accent)
        selection = UIColor(palette.accent).withAlphaComponent(TerminalPage.selectionOpacity)
        indicator = palette.isDark ? .white : .black
    }

    /// Draw a terminal view in these colours, at once.
    ///
    /// - Parameter view: The view.
    func paint(_ view: TerminalView) {
        let installed = ansi.map { hex in
            SwiftTerm.Color(
                red8: UInt16((hex >> 16) & 0xFF), green8: UInt16((hex >> 8) & 0xFF), blue8: UInt16(hex & 0xFF))
        }
        view.getTerminal().ansi256PaletteStrategy = .xterm
        view.installColors(installed)
        view.nativeBackgroundColor = background
        view.nativeForegroundColor = foreground
        view.layer.backgroundColor = background.cgColor
        view.caretColor = cursor
        view.selectedTextBackgroundColor = selection
        view.selectedTextForegroundColor = foreground
        view.indicatorStyle = indicator
    }
}

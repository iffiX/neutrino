import SwiftUI

/// One palette: the panel's colour tokens, under the names the panel's CSS gives them. Accent is what a page is
/// for and what is selected; ok is on and healthy; warn is a step in flight; error is failed and the
/// destructive action. The signal colours carry no text and draw the status dots.
struct NeutrinoPalette {
    let bg: Color
    let surface: Color
    let elevated: Color
    let border: Color
    let borderStrong: Color
    let text: Color
    let textMuted: Color
    let textFaint: Color
    let accent: Color
    let ok: Color
    let warn: Color
    let error: Color
    let signalOk: Color
    let signalWarn: Color
    let signalError: Color
    let termBg: Color
    let termFg: Color
    let isDark: Bool

    /// The accent at 12 %, behind a selected or primary control.
    var accentWash: Color { accent.opacity(0.12) }

    /// The error colour at 12 %, behind a destructive confirmation.
    var errorWash: Color { error.opacity(0.12) }

    /// The dark palette.
    static let dark = NeutrinoPalette(
        bg: Color(hex: 0x070809),
        surface: Color(hex: 0x0E1013),
        elevated: Color(hex: 0x15181C),
        border: Color(hex: 0x1C2026),
        borderStrong: Color(hex: 0x2A3038),
        text: Color(hex: 0xE6EDF3),
        textMuted: Color(hex: 0x8B96A5),
        textFaint: Color(hex: 0x5B6675),
        accent: Color(hex: 0x22D3EE),
        ok: Color(hex: 0x34D399),
        warn: Color(hex: 0xFBBF24),
        error: Color(hex: 0xFB7185),
        signalOk: Color(hex: 0x34D399),
        signalWarn: Color(hex: 0xFBBF24),
        signalError: Color(hex: 0xFB7185),
        termBg: Color(hex: 0x070809),
        termFg: Color(hex: 0xE6EDF3),
        isDark: true)

    /// The light palette.
    static let light = NeutrinoPalette(
        bg: Color(hex: 0xE8EBF0),
        surface: Color(hex: 0xF6F7F9),
        elevated: Color(hex: 0xDDE2E8),
        border: Color(hex: 0xCDD4DC),
        borderStrong: Color(hex: 0xB4BFCB),
        text: Color(hex: 0x0F172A),
        textMuted: Color(hex: 0x5B6675),
        textFaint: Color(hex: 0x7B8794),
        accent: Color(hex: 0x0C6A84),
        ok: Color(hex: 0x046A4D),
        warn: Color(hex: 0xA34A07),
        error: Color(hex: 0xB10F38),
        signalOk: Color(hex: 0x10B981),
        signalWarn: Color(hex: 0xF59E0B),
        signalError: Color(hex: 0xEF4444),
        termBg: Color(hex: 0x0F172A),
        termFg: Color(hex: 0xE6EDF3),
        isDark: false)
}

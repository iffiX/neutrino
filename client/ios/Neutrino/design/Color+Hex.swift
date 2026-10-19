import SwiftUI

extension Color {
    /// A colour from its RGB value, as the panel's themes write it.
    ///
    /// - Parameters:
    ///   - hex: The red, green and blue bytes, `0xRRGGBB`.
    ///   - opacity: The opacity, from 0 to 1.
    init(hex: UInt32, opacity: Double = 1) {
        self.init(
            .sRGB,
            red: Double((hex >> 16) & 0xFF) / 255,
            green: Double((hex >> 8) & 0xFF) / 255,
            blue: Double(hex & 0xFF) / 255,
            opacity: opacity)
    }
}

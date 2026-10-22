import SwiftUI

/// A round button of one icon, as the remote desktop viewer draws its Keyboard, Keys and Close: translucent, in
/// the accent while pressed, and in the error colour for a danger.
struct RoundButton: View {
    /// The SF Symbol it shows.
    let systemImage: String

    /// What VoiceOver reads.
    let label: String

    /// Its diameter, in points.
    var size = 36.0

    /// Whether it shows pressed.
    var isActive = false

    /// Whether it ends something.
    var isDanger = false

    /// Whether it can act.
    var isEnabled = true

    /// What a press does.
    let action: () -> Void

    @Environment(\.palette) private var palette

    var body: some View {
        let tone = isDanger ? palette.error : isActive ? palette.accent : palette.text
        Button(action: action) {
            Image(systemName: systemImage)
                .font(.system(size: size * 15 / 36, weight: .semibold))
                .foregroundColor(tone)
                .frame(width: size, height: size)
                .background(Circle().fill(palette.surface.opacity(0.6)))
                .background(Circle().fill(isActive ? palette.accentWash : .clear))
                .overlay(
                    Circle().stroke(isActive || isDanger ? tone : palette.borderStrong.opacity(0.6), lineWidth: 1))
        }
        .buttonStyle(.plain)
        .disabled(!isEnabled)
        .opacity(isEnabled ? 1 : 0.4)
        .accessibilityLabel(label)
    }
}

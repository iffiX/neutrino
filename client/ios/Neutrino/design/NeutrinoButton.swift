import SwiftUI

/// A button in one of the panel's tiers: while its job runs it shows a spinner and the job's word, and it is
/// disabled.
struct NeutrinoButton: View {
    /// The label, or the job's word while it runs.
    let label: String

    /// The tier.
    var tier = ButtonTier.plain

    /// Whether the button's job runs.
    var isBusy = false

    /// Whether the button can act.
    var isEnabled = true

    /// Whether the button is armed: the second press acts.
    var isArmed = false

    /// What a press does.
    let action: () -> Void

    @Environment(\.palette) private var palette

    var body: some View {
        Button(action: action) {
            HStack(spacing: 6) {
                if isBusy {
                    ProgressView().controlSize(.mini).tint(palette.signalWarn)
                }
                Text(label).font(.system(size: 13, weight: .medium)).lineLimit(1)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 6)
            .foregroundColor(foreground)
            .background(RoundedRectangle(cornerRadius: 6).fill(fill))
            .overlay(RoundedRectangle(cornerRadius: 6).stroke(stroke, lineWidth: 1))
        }
        .buttonStyle(.plain)
        .disabled(!isEnabled || isBusy)
    }

    private var isLive: Bool { isEnabled && !isBusy }

    private var foreground: Color {
        if !isLive { return palette.textFaint }
        if isArmed { return palette.error }
        switch tier {
        case .primary: return palette.accent
        case .danger: return palette.error
        case .plain, .ghost: return palette.text
        }
    }

    private var fill: Color {
        if isArmed { return palette.errorWash }
        return tier == .primary && isLive ? palette.accentWash : .clear
    }

    private var stroke: Color {
        if isArmed { return palette.error }
        switch tier {
        case .primary: return isLive ? palette.accent.opacity(0.6) : palette.border
        case .danger: return isLive ? palette.error.opacity(0.7) : palette.border
        case .plain: return palette.borderStrong
        case .ghost: return .clear
        }
    }
}

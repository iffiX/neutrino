import SwiftUI

/// A row's status marker: a dot in its tone, pulsing while something runs.
struct StatusDot: View {
    /// The tone.
    let tone: DotTone

    @Environment(\.palette) private var palette
    @State private var isDim = false

    var body: some View {
        Circle()
            .fill(color)
            .frame(width: 8, height: 8)
            .opacity(tone == .pulse && isDim ? 0.3 : 1)
            .onAppear { startPulse() }
            .onChange(of: tone == .pulse) { _ in startPulse() }
    }

    private var color: Color {
        switch tone {
        case .ok: return palette.signalOk
        case .wait, .pulse: return palette.signalWarn
        case .bad: return palette.signalError
        case .off: return palette.textMuted
        }
    }

    private func startPulse() {
        guard tone == .pulse else {
            isDim = false
            return
        }
        withAnimation(.linear(duration: 0.8).repeatForever(autoreverses: true)) { isDim = true }
    }
}

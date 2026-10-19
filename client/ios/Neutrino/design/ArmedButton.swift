import SwiftUI

/// A destructive button: the first press arms it, its label turning to the armed sentence and its fill red, and
/// a second press within five seconds acts.
struct ArmedButton: View {
    /// The button's key among every armed button of the app.
    let key: String

    /// The label.
    let label: String

    /// The label while armed.
    let armedLabel: String

    /// Whether the button's job runs.
    var isBusy = false

    /// Whether the button can act.
    var isEnabled = true

    /// What the second press does.
    let onAct: () -> Void

    @EnvironmentObject private var arm: ArmState

    var body: some View {
        let isArmed = arm.armed == key
        NeutrinoButton(
            label: isArmed ? armedLabel : label, tier: .danger, isBusy: isBusy, isEnabled: isEnabled,
            isArmed: isArmed
        ) {
            if isArmed {
                arm.disarm()
                onAct()
            } else {
                arm.arm(key)
            }
        }
    }
}

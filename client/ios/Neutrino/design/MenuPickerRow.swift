import SwiftUI

/// A picker drawn as a row: its name at the left, and at the right the chosen value in the same size, in the
/// accent, with the up-and-down chevrons. A press opens the system's menu of the choices, the chosen one checked.
struct MenuPickerRow<Value: Hashable>: View {
    /// The picker's name.
    let label: String

    /// The choices, in their order.
    let options: [Value]

    /// The words a choice is shown with.
    let name: (Value) -> String

    /// The chosen value.
    @Binding var selection: Value

    @Environment(\.palette) private var palette

    var body: some View {
        HStack {
            Text(label).font(.system(size: 14)).foregroundColor(palette.text)
            Spacer()
            Menu {
                Picker(label, selection: $selection) {
                    ForEach(options, id: \.self) { option in Text(name(option)).tag(option) }
                }
            } label: {
                HStack(spacing: 4) {
                    Text(name(selection)).font(.system(size: 14))
                    Image(systemName: "chevron.up.chevron.down").font(.system(size: 10, weight: .semibold))
                }
                .foregroundColor(palette.accent)
            }
            .tint(palette.accent)
        }
    }
}

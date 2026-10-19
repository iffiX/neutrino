import Foundation

/// A page's own action, such as New terminal or Scan: at the right of the page header beside the sidebar, and a
/// floating button at the bottom right above the bottom bar.
struct PageAction: Equatable {
    /// The label.
    let label: String

    /// The SF Symbol it shows.
    let systemImage: String

    /// Whether it can act.
    let isEnabled: Bool

    /// What a press does.
    let action: () -> Void

    static func == (left: PageAction, right: PageAction) -> Bool {
        left.label == right.label && left.systemImage == right.systemImage && left.isEnabled == right.isEnabled
    }
}

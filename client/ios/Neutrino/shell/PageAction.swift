import Foundation

/// A page's own action, such as New terminal or Scan: at the right of the page header beside the sidebar, and a
/// floating button at the bottom right above the bottom bar. An action with items is the one floating button of
/// several: a menu of its items above the bottom bar, and each item a button of the header beside the sidebar.
struct PageAction: Equatable {
    /// The label.
    let label: String

    /// The SF Symbol it shows.
    let systemImage: String

    /// Whether it can act.
    let isEnabled: Bool

    /// What a press does.
    let action: () -> Void

    /// The actions its floating button's menu holds; empty for an action of its own.
    var items: [PageAction] = []

    static func == (left: PageAction, right: PageAction) -> Bool {
        left.label == right.label && left.systemImage == right.systemImage && left.isEnabled == right.isEnabled
            && left.items == right.items
    }
}

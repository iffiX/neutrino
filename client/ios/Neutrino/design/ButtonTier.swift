import Foundation

/// The panel's button tiers.
enum ButtonTier {
    /// Bordered: a standalone secondary action.
    case plain
    /// Accent: the action a page or a section exists for.
    case primary
    /// Borderless: a repeated row action, or the Cancel beside a primary.
    case ghost
    /// Red outline: an action that removes something.
    case danger
}

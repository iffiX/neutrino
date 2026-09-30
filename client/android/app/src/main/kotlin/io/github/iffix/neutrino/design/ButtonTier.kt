package io.github.iffix.neutrino.design

/** The panel's button tiers. */
enum class ButtonTier {
    /** Bordered: a standalone secondary action. */
    PLAIN,

    /** Accent: the action a screen or a section exists for. */
    PRIMARY,

    /** Borderless: a repeated row action, or the Cancel beside a primary. */
    GHOST,

    /** Red outline: an action that removes something. */
    DANGER,
}

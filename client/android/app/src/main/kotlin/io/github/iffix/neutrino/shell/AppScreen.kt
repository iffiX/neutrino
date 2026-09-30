package io.github.iffix.neutrino.shell

import io.github.iffix.neutrino.design.AppIcon

/**
 * A screen the app shows, with the words of its title and the icon of its tab.
 *
 * @property route The navigation route.
 * @property titleKey The catalog key of its title.
 * @property icon Its tab's icon, or null for a screen reached from another.
 * @property parent The tab a screen reached from another belongs to, for the back arrow.
 */
enum class AppScreen(val route: String, val titleKey: String, val icon: AppIcon?, val parent: AppScreen? = null) {
    HUBS("hubs", "ui.section_hubs", AppIcon.SERVER),
    WEB("web", "ui.panel_web", AppIcon.GLOBE),
    PORTS("ports", "ui.panel_ports", AppIcon.PLUG),
    AI("ai", "ui.panel_ai", AppIcon.SPARKLES),
    FILES("files", "ui.panel_files", AppIcon.FOLDER),
    TERMINALS("terminals", "ui.panel_terminals", AppIcon.TERMINAL),
    REMOTE_DESKTOP("remote_desktop", "ui.panel_desktops", AppIcon.DESKTOP),
    SETTINGS("settings", "ui.settings", AppIcon.SETTINGS),
    JOIN("join", "ui.add_hub", null, HUBS),
    ABOUT("about", "ui.about", null, SETTINGS),
    ;

    companion object {
        /** The screens that have a tab, in the order the bars draw them. */
        val tabs: List<AppScreen> = entries.filter { it.icon != null }

        /**
         * The screen a route names.
         *
         * @param route A navigation route, or null.
         * @return The screen, or [HUBS] when the route names none.
         */
        fun of(route: String?): AppScreen = entries.firstOrNull { it.route == route } ?: HUBS
    }
}

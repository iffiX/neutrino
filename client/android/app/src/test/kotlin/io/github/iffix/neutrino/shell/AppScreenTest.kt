package io.github.iffix.neutrino.shell

import org.junit.Assert.assertEquals
import org.junit.Test

class AppScreenTest {
    @Test
    fun theBarsDrawTheSixTabsInTheDemosOrder() {
        assertEquals(
            listOf("hubs", "apps", "files", "terminals", "remote_desktop", "settings"),
            AppScreen.tabs.map { it.route },
        )
    }

    @Test
    fun theBottomBarLabelsRemoteDesktopsAsDesktops() {
        assertEquals(
            listOf(
                "ui.section_hubs",
                "ui.panel_apps",
                "ui.panel_files",
                "ui.panel_terminals",
                "ui.bar_desktops",
                "ui.settings",
            ),
            AppScreen.tabs.map { it.barKey },
        )
    }

    @Test
    fun aScreenReachedFromAnotherBelongsToItsTab() {
        assertEquals(AppScreen.HUBS, AppScreen.JOIN.parent)
        assertEquals(listOf(AppScreen.JOIN), AppScreen.entries.filter { it.icon == null })
    }

    @Test
    fun anUnknownRouteOpensTheHubs() {
        assertEquals(AppScreen.HUBS, AppScreen.of(null))
        assertEquals(AppScreen.HUBS, AppScreen.of("nowhere"))
        assertEquals(AppScreen.HUBS, AppScreen.of("ai"))
        assertEquals(AppScreen.FILES, AppScreen.of("files"))
    }
}

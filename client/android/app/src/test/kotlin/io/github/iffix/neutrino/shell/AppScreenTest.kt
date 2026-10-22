package io.github.iffix.neutrino.shell

import org.junit.Assert.assertEquals
import org.junit.Test

class AppScreenTest {
    @Test
    fun theBarsDrawTheSixTabsInTheDemosOrder() {
        assertEquals(
            listOf("hubs", "web", "files", "terminals", "remote_desktop", "settings"),
            AppScreen.tabs.map { it.route },
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

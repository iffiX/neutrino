package io.github.iffix.neutrino.screen

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import io.github.iffix.neutrino.CLIENT_CARRIED_CORES
import io.github.iffix.neutrino.CLIENT_RUSTDESK_CORE
import io.github.iffix.neutrino.CLIENT_RUSTDESK_PATCH_URL
import io.github.iffix.neutrino.CLIENT_RUSTDESK_SOURCE_URL
import io.github.iffix.neutrino.design.Badge
import io.github.iffix.neutrino.design.FeatureRow
import io.github.iffix.neutrino.design.NeutrinoPalette
import io.github.iffix.neutrino.design.NeutrinoTheme
import io.github.iffix.neutrino.design.ScreenColumn
import io.github.iffix.neutrino.design.SurfaceCard
import io.github.iffix.neutrino.words.WordCatalog

/**
 * The app's name, version and licence, and each core it carries with its version and licence.
 *
 * @param version The app's version.
 */
@Composable
fun AboutScreen(version: String) {
    val words = NeutrinoTheme.words
    val palette = NeutrinoTheme.palette
    ScreenColumn {
        SurfaceCard {
            FeatureRow {
                BasicText(words.word("ui.window.title"), style = NeutrinoTheme.rowTitle)
                BasicText(words.word("ui.about_version", mapOf("version" to version)), style = NeutrinoTheme.mono)
                BasicText(words.word("ui.app_licence"), style = NeutrinoTheme.note)
            }
            FeatureRow(hasDivider = false) {
                BasicText(
                    words.word("ui.carried_cores"),
                    style = NeutrinoTheme.note,
                    modifier = Modifier.padding(bottom = 6.dp),
                )
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    for ((name, coreVersion, licence) in CLIENT_CARRIED_CORES) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.spacedBy(8.dp),
                            verticalAlignment = Alignment.CenterVertically,
                        ) {
                            BasicText(name, style = NeutrinoTheme.body)
                            BasicText(
                                coreVersion,
                                style = NeutrinoTheme.mono.copy(color = palette.textFaint),
                                modifier = Modifier.weight(1f),
                            )
                            Badge(licence)
                        }
                        if (name == CLIENT_RUSTDESK_CORE) {
                            Row(horizontalArrangement = Arrangement.spacedBy(16.dp)) {
                                SourceLink(words.word("ui.core_source"), CLIENT_RUSTDESK_SOURCE_URL)
                                SourceLink(
                                    words.word("ui.core_patch"),
                                    CLIENT_RUSTDESK_PATCH_URL.replace("{version}", version),
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun SourceLink(label: String, url: String) {
    val uriHandler = LocalUriHandler.current
    BasicText(
        label,
        style = NeutrinoTheme.note.copy(color = NeutrinoTheme.palette.accent),
        modifier = Modifier.clickable { uriHandler.openUri(url) },
    )
}

@Preview(widthDp = 400, heightDp = 500)
@Composable
private fun AboutScreenPreview() {
    val words = WordCatalog(
        mapOf(
            "ui.window.title" to "微子·客户端",
            "ui.about_version" to "{version} · Android",
            "ui.app_licence" to "许可 AGPL-3.0",
            "ui.carried_cores" to "随 app 携带的核心",
            "ui.core_source" to "源码 1.4.9",
            "ui.core_patch" to "补丁",
        ),
    )
    NeutrinoTheme(NeutrinoPalette.dark, words) { AboutScreen("0.5.0") }
}

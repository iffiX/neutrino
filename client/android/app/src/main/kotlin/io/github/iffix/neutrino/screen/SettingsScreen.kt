package io.github.iffix.neutrino.screen

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import io.github.iffix.neutrino.CLIENT_CARRIED_CORES
import io.github.iffix.neutrino.CLIENT_LANGUAGES
import io.github.iffix.neutrino.CLIENT_LICENCE
import io.github.iffix.neutrino.CLIENT_SOURCE_URL
import io.github.iffix.neutrino.CLIENT_THEMES
import io.github.iffix.neutrino.design.ButtonTier
import io.github.iffix.neutrino.design.NeutrinoButton
import io.github.iffix.neutrino.design.NeutrinoPalette
import io.github.iffix.neutrino.design.NeutrinoTheme
import io.github.iffix.neutrino.design.PickerField
import io.github.iffix.neutrino.design.ScreenColumn
import io.github.iffix.neutrino.design.SurfaceCard
import io.github.iffix.neutrino.settings.ClientSettings
import io.github.iffix.neutrino.words.WordCatalog

/**
 * Two cards: the language and the theme, staged until saved, and About, one row per fact: this
 * phone's name and platform, the app's version and licence, the source links, and each core the
 * app carries with its version and patch.
 *
 * @param saved The settings in force.
 * @param deviceName This phone's name.
 * @param platform This phone's platform.
 * @param version The app's version.
 * @param onSave What saving the staged settings does.
 */
@Composable
fun SettingsScreen(
    saved: ClientSettings,
    deviceName: String,
    platform: String,
    version: String,
    onSave: (ClientSettings) -> Unit,
) {
    val words = NeutrinoTheme.words
    var draft by remember(saved) { mutableStateOf(saved) }
    val isDirty = draft != saved
    ScreenColumn {
        SurfaceCard(isDirty = isDirty) {
            Column(modifier = Modifier.padding(vertical = 12.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    BasicText(words.word("ui.language"), style = NeutrinoTheme.fieldLabel)
                    PickerField(
                        options = CLIENT_LANGUAGES.map { it to words.word("ui.language_name.$it") },
                        selected = draft.language,
                        onSelect = { draft = draft.copy(language = it) },
                    )
                }
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    BasicText(words.word("ui.theme"), style = NeutrinoTheme.fieldLabel)
                    PickerField(
                        options = CLIENT_THEMES.map { it to words.word("ui.theme_name.$it") },
                        selected = draft.theme,
                        onSelect = { draft = draft.copy(theme = it) },
                    )
                }
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.spacedBy(8.dp, Alignment.End),
                ) {
                    NeutrinoButton(
                        words.word("ui.cancel"),
                        onClick = { draft = saved },
                        tier = ButtonTier.GHOST,
                        isEnabled = isDirty,
                    )
                    NeutrinoButton(
                        words.word("ui.save"),
                        onClick = { onSave(draft) },
                        tier = ButtonTier.PRIMARY,
                        isCommit = true,
                        isEnabled = isDirty,
                    )
                }
            }
        }
        AboutCard(deviceName, platform, version)
    }
}

@Composable
private fun AboutCard(deviceName: String, platform: String, version: String) {
    val words = NeutrinoTheme.words
    val rows = buildList {
        add(AboutFact(words.word("ui.about_device"), deviceName))
        add(AboutFact(words.word("ui.about_platform"), platform))
        add(AboutFact(words.word("ui.about_version"), version))
        add(AboutFact(words.word("ui.about_licence"), CLIENT_LICENCE))
        add(AboutFact(words.word("ui.about_source", mapOf("name" to "Neutrino")), CLIENT_SOURCE_URL, isLink = true))
        for (core in CLIENT_CARRIED_CORES) {
            add(AboutFact(words.word("ui.about_core", mapOf("name" to core.name)), "${core.version} · ${core.licence}"))
            add(AboutFact(words.word("ui.about_source", mapOf("name" to core.name)), core.sourceUrl, isLink = true))
            if (core.patchUrl.isNotEmpty()) {
                val patch = core.patchUrl.replace("{version}", version)
                add(AboutFact(words.word("ui.about_patch", mapOf("name" to core.name)), patch, isLink = true))
            }
        }
    }
    SurfaceCard {
        BasicText(
            words.word("ui.about"),
            style = NeutrinoTheme.rowTitle,
            modifier = Modifier.padding(top = 12.dp, bottom = 4.dp),
        )
        for ((index, fact) in rows.withIndex()) AboutRow(fact, hasDivider = index < rows.lastIndex)
    }
}

@Composable
private fun AboutRow(fact: AboutFact, hasDivider: Boolean) {
    val palette = NeutrinoTheme.palette
    val uriHandler = LocalUriHandler.current
    var row = Modifier.fillMaxWidth()
    if (hasDivider) {
        row = row.drawBehind {
            drawLine(palette.border, Offset(0f, size.height), Offset(size.width, size.height), 1.dp.toPx())
        }
    }
    if (fact.isLink) row = row.clickable(role = Role.Button) { uriHandler.openUri(fact.value) }
    Row(
        modifier = row.padding(vertical = 10.dp),
        horizontalArrangement = Arrangement.spacedBy(16.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        BasicText(fact.label, style = NeutrinoTheme.note.copy(color = palette.textMuted))
        BasicText(
            if (fact.isLink) fact.value.removePrefix("https://") else fact.value,
            style = NeutrinoTheme.mono.copy(
                color = if (fact.isLink) palette.accent else palette.text,
                textAlign = TextAlign.End,
            ),
            modifier = Modifier.weight(1f),
        )
    }
}

/** One row of the About card: a fact's label, and its value or the address it links. */
private data class AboutFact(val label: String, val value: String, val isLink: Boolean = false)

@Preview(widthDp = 400, heightDp = 700)
@Composable
private fun SettingsScreenPreview() {
    val words = WordCatalog(
        mapOf(
            "ui.language" to "语言",
            "ui.theme" to "主题",
            "ui.language_name.zh-CN" to "简体中文",
            "ui.theme_name.system" to "跟随系统",
            "ui.cancel" to "取消",
            "ui.save" to "保存",
            "ui.about" to "关于",
            "ui.about_device" to "本机",
            "ui.about_version" to "版本",
        ),
    )
    NeutrinoTheme(NeutrinoPalette.dark, words) {
        SettingsScreen(
            ClientSettings("zh-CN", "system"),
            deviceName = "Pixel 8",
            platform = "android/arm64 · Android 15",
            version = "0.5.0",
            onSave = {},
        )
    }
}

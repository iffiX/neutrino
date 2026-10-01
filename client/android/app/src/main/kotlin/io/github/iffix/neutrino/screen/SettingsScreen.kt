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
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import io.github.iffix.neutrino.CLIENT_CARRIED_CORES
import io.github.iffix.neutrino.CLIENT_LANGUAGES
import io.github.iffix.neutrino.CLIENT_RUSTDESK_CORE
import io.github.iffix.neutrino.CLIENT_RUSTDESK_PATCH_URL
import io.github.iffix.neutrino.CLIENT_RUSTDESK_SOURCE_URL
import io.github.iffix.neutrino.CLIENT_SOURCE_URL
import io.github.iffix.neutrino.CLIENT_THEMES
import io.github.iffix.neutrino.design.Badge
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
 * The language and the theme, staged until saved, and under the card the About section: the
 * version, the licence, the source links, and the cores the app carries with their patches.
 *
 * @param saved The settings in force.
 * @param version The app's version.
 * @param onSave What saving the staged settings does.
 */
@Composable
fun SettingsScreen(saved: ClientSettings, version: String, onSave: (ClientSettings) -> Unit) {
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
        AboutSection(version)
    }
}

@Composable
private fun AboutSection(version: String) {
    val words = NeutrinoTheme.words
    val palette = NeutrinoTheme.palette
    Column(modifier = Modifier.padding(horizontal = 4.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        BasicText(words.word("ui.about"), style = NeutrinoTheme.rowTitle)
        BasicText(words.word("ui.window.title"), style = NeutrinoTheme.body)
        BasicText(words.word("ui.about_build", mapOf("version" to version)), style = NeutrinoTheme.mono)
        BasicText(words.word("ui.app_licence"), style = NeutrinoTheme.note)
        SourceLink(words.word("ui.about_source", mapOf("name" to words.word("ui.window.title"))), CLIENT_SOURCE_URL)
        BasicText(
            words.word("ui.carried_cores"),
            style = NeutrinoTheme.note,
            modifier = Modifier.padding(top = 6.dp),
        )
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
                    SourceLink(words.word("ui.core_patch"), CLIENT_RUSTDESK_PATCH_URL.replace("{version}", version))
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
        modifier = Modifier.clickable(role = Role.Button) { uriHandler.openUri(url) },
    )
}

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
            "ui.about_build" to "{version} · Android",
        ),
    )
    NeutrinoTheme(NeutrinoPalette.dark, words) {
        SettingsScreen(ClientSettings("zh-CN", "system"), version = "0.5.0", onSave = {})
    }
}

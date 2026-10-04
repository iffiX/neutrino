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
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import io.github.iffix.neutrino.CLIENT_LANGUAGES
import io.github.iffix.neutrino.CLIENT_LICENCE
import io.github.iffix.neutrino.CLIENT_THEMES
import io.github.iffix.neutrino.Edition
import io.github.iffix.neutrino.design.ButtonTier
import io.github.iffix.neutrino.design.CardHeader
import io.github.iffix.neutrino.design.NeutrinoButton
import io.github.iffix.neutrino.design.NeutrinoPalette
import io.github.iffix.neutrino.design.NeutrinoTheme
import io.github.iffix.neutrino.design.PickerField
import io.github.iffix.neutrino.design.ScreenColumn
import io.github.iffix.neutrino.design.SectionLabel
import io.github.iffix.neutrino.design.SurfaceCard
import io.github.iffix.neutrino.settings.ClientSettings
import io.github.iffix.neutrino.words.WordCatalog

/**
 * Two cards, in the panel's order: About, the panel's About card in two groups (this phone's name
 * and platform; the app and each core it carries as a credits row, its name and version, its
 * licence and the Source and Patch links), then the language and the theme, staged until saved.
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
        AboutCard(deviceName, platform, version)
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
    }
}

@Composable
private fun AboutCard(deviceName: String, platform: String, version: String) {
    val words = NeutrinoTheme.words
    val source = words.word("ui.about_source_link")
    val patch = words.word("ui.about_patch_link")
    val machine = listOf(
        AboutFact(words.word("ui.about_machine"), deviceName),
        AboutFact(words.word("ui.about_platform"), platform),
    )
    val carried = buildList {
        add(
            AboutFact(
                "${words.word("ui.window.title")} $version",
                CLIENT_LICENCE,
                links = listOf(source to Edition.sourceUrl),
            ),
        )
        for (core in Edition.carriedCores) {
            val links = buildList {
                add(source to core.sourceUrl)
                if (core.patchUrl.isNotEmpty()) {
                    add(patch to core.patchUrl.replace("{source}", Edition.sourceUrl).replace("{version}", version))
                }
            }
            add(AboutFact("${core.name} ${core.version}", core.licence, links))
        }
    }
    val groups = listOf(
        words.word("ui.about_this_machine") to machine,
        words.word("ui.about_carried") to carried,
    )
    val last = carried.last()
    SurfaceCard {
        Column(modifier = Modifier.padding(vertical = 12.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            CardHeader(words.word("ui.about"))
            for ((index, group) in groups.withIndex()) {
                SectionLabel(group.first, modifier = Modifier.padding(top = if (index == 0) 0.dp else 12.dp))
                for (fact in group.second) AboutRow(fact, hasDivider = fact !== last)
            }
        }
    }
}

@Composable
private fun AboutRow(fact: AboutFact, hasDivider: Boolean) {
    val palette = NeutrinoTheme.palette
    val uriHandler = LocalUriHandler.current
    val rule = palette.border.copy(alpha = palette.border.alpha * 0.6f)
    val value = NeutrinoTheme.mono.copy(color = palette.text, fontSize = 12.5.sp)
    var row = Modifier.fillMaxWidth()
    if (hasDivider) {
        row = row.drawBehind {
            drawLine(rule, Offset(0f, size.height), Offset(size.width, size.height), 1.dp.toPx())
        }
    }
    Row(
        modifier = row.padding(vertical = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(16.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        BasicText(fact.label, style = NeutrinoTheme.note, modifier = Modifier.weight(1f))
        Row(verticalAlignment = Alignment.CenterVertically) {
            BasicText(if (fact.links.isEmpty()) fact.value else "${fact.value} — ", style = value)
            for ((index, link) in fact.links.withIndex()) {
                if (index > 0) BasicText(" · ", style = value)
                BasicText(
                    link.first,
                    style = value.copy(color = palette.accent),
                    modifier = Modifier.clickable(role = Role.Button) { uriHandler.openUri(link.second) },
                )
            }
        }
    }
}

/**
 * One row of the About card.
 *
 * @property label What the row is about, at the left.
 * @property value Its value, at the right.
 * @property links The link words after the value, each with the address it opens.
 */
private data class AboutFact(val label: String, val value: String, val links: List<Pair<String, String>> = emptyList())

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
            "ui.about_machine" to "本机名称",
            "ui.about_this_machine" to "本机",
            "ui.about_carried" to "携带",
            "ui.about_source_link" to "源码",
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

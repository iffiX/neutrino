package io.github.iffix.neutrino.screen

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.selection.toggleable
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.semantics.Role
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.channel.HubView
import io.github.iffix.neutrino.design.AppIcon
import io.github.iffix.neutrino.design.Badge
import io.github.iffix.neutrino.design.ButtonTier
import io.github.iffix.neutrino.design.DotTone
import io.github.iffix.neutrino.design.FeatureRow
import io.github.iffix.neutrino.design.InputField
import io.github.iffix.neutrino.design.NeutrinoButton
import io.github.iffix.neutrino.design.NeutrinoTheme
import io.github.iffix.neutrino.design.PickerField
import io.github.iffix.neutrino.design.StatusDot
import io.github.iffix.neutrino.files.ShareLogin
import io.github.iffix.neutrino.files.ShareRoot
import kotlinx.coroutines.launch

/**
 * The shares the joined hubs publish, each a place in the system's Files: the password is asked
 * once, here, and kept in the Keystore when the person says so.
 *
 * @param hubs Every hub joined.
 * @param hasLogin Whether a share has a login already, by its root id.
 * @param onLogin What giving a login does: it is tried on the server, then kept; the refusal when it fails.
 * @param onOpen What opening a share in Files does, with its root id.
 * @param onJoin What pressing Join a hub does.
 */
@Composable
fun FilesScreen(
    hubs: List<HubView>,
    hasLogin: (String) -> Boolean,
    onLogin: suspend (ShareRoot, ShareLogin, Boolean) -> ChannelResult<Unit>,
    onOpen: (String) -> Unit,
    onJoin: () -> Unit,
) {
    val words = NeutrinoTheme.words
    var asking by remember { mutableStateOf("") }
    ServiceList(hubs, "file", "ui.empty_files", onJoin) { hub, entry, hasDivider ->
        val root = ShareRoot.of(hub, entry) ?: return@ServiceList
        val isKept = hasLogin(root.key)
        FeatureRow(marker = if (entry.isHealthy == false) DotTone.BAD else DotTone.OK, hasDivider = hasDivider) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                BasicText(entry.title, style = NeutrinoTheme.rowTitle)
                if (!isKept) Badge(words.word("ui.password_not_saved"), icon = AppIcon.LOCK)
            }
            BasicText("smb://${root.host}/${root.share}", style = NeutrinoTheme.mono)
            BasicText(providedBy(hub, entry, root.host), style = NeutrinoTheme.note)
            if (asking == root.key) {
                LoginForm(root, onLogin, onDone = {
                    asking = ""
                    onOpen(root.key)
                }) { asking = "" }
            } else {
                Row(modifier = Modifier.padding(top = 8.dp)) {
                    NeutrinoButton(
                        words.word("ui.open_in_files"),
                        { if (isKept) onOpen(root.key) else asking = root.key },
                        icon = AppIcon.FOLDER,
                        isSmall = true,
                    )
                }
            }
        }
    }
}

@Composable
private fun LoginForm(
    root: ShareRoot,
    onLogin: suspend (ShareRoot, ShareLogin, Boolean) -> ChannelResult<Unit>,
    onDone: () -> Unit,
    onCancel: () -> Unit,
) {
    val words = NeutrinoTheme.words
    val palette = NeutrinoTheme.palette
    val scope = rememberCoroutineScope()
    var user by remember { mutableStateOf(root.users.firstOrNull().orEmpty()) }
    var password by remember { mutableStateOf("") }
    var isKept by remember { mutableStateOf(true) }
    var isTrying by remember { mutableStateOf(false) }
    var refusal by remember { mutableStateOf<ChannelResult.Refused?>(null) }
    val shape = RoundedCornerShape(10.dp)
    val connect = {
        if (password.isNotEmpty() && user.isNotEmpty() && !isTrying) {
            isTrying = true
            refusal = null
            scope.launch {
                val answer = onLogin(root, ShareLogin(user, password), isKept)
                isTrying = false
                if (answer is ChannelResult.Refused) refusal = answer else onDone()
            }
        }
    }
    Column(
        modifier = Modifier
            .padding(top = 12.dp)
            .fillMaxWidth()
            .clip(shape)
            .background(palette.bg)
            .border(1.dp, palette.border, shape)
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            BasicText(words.word("ui.username_hint"), style = NeutrinoTheme.fieldLabel)
            if (root.users.size > 1) {
                PickerField(root.users.map { it to it }, user, onSelect = { user = it })
            } else {
                InputField(user, { user = it }, words.word("ui.username_hint"), modifier = Modifier.fillMaxWidth())
            }
        }
        Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
            BasicText(words.word("ui.password_hint"), style = NeutrinoTheme.fieldLabel)
            InputField(
                password,
                { password = it },
                words.word("ui.password_hint"),
                modifier = Modifier.fillMaxWidth(),
                isSecret = true,
                onDone = { connect() },
            )
        }
        Row(
            modifier = Modifier.toggleable(value = isKept, role = Role.Checkbox) { isKept = it },
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            val box = RoundedCornerShape(4.dp)
            BasicText(
                if (isKept) "✓" else " ",
                style = NeutrinoTheme.note.copy(color = palette.accent),
                modifier = Modifier
                    .clip(box)
                    .border(1.dp, if (isKept) palette.accent else palette.borderStrong, box)
                    .padding(horizontal = 4.dp),
            )
            BasicText(words.word("ui.remember"), style = NeutrinoTheme.body)
        }
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            NeutrinoButton(
                words.word("ui.port_connect"),
                { connect() },
                tier = ButtonTier.PRIMARY,
                isEnabled = password.isNotEmpty() && user.isNotEmpty() && !isTrying,
            )
            NeutrinoButton(words.word("ui.cancel"), onCancel, tier = ButtonTier.GHOST)
            if (isTrying) StatusDot(DotTone.SPIN)
        }
        refusal?.let {
            BasicText(words.refusal(it.code, it.wordParams), style = NeutrinoTheme.note.copy(color = palette.error))
        }
    }
}

@Preview(widthDp = 400, heightDp = 600)
@Composable
private fun FilesScreenPreview() {
    PreviewHubs.Frame(mapOf("ui.open_in_files" to "在“文件”中打开", "ui.password_not_saved" to "未存密码")) {
        FilesScreen(PreviewHubs.all, hasLogin = {
            false
        }, onLogin = { _, _, _ -> ChannelResult.Ok(Unit) }, onOpen = {}, onJoin = {})
    }
}

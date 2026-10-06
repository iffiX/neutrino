package io.github.iffix.neutrino.files

import android.database.Cursor
import android.database.MatrixCursor
import android.os.Bundle
import android.os.CancellationSignal
import android.os.Handler
import android.os.HandlerThread
import android.os.ParcelFileDescriptor
import android.os.ProxyFileDescriptorCallback
import android.os.storage.StorageManager
import android.provider.DocumentsContract.Document
import android.provider.DocumentsContract.Root
import android.provider.DocumentsProvider
import android.system.ErrnoException
import android.system.OsConstants
import android.webkit.MimeTypeMap
import io.github.iffix.neutrino.ConnectRefusedException
import io.github.iffix.neutrino.NeutrinoApplication
import io.github.iffix.neutrino.R
import io.github.iffix.neutrino.ShareRefusedException
import io.github.iffix.neutrino.ShareUnreachableException
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.words.WordCatalog
import java.io.FileNotFoundException
import java.io.IOException

/**
 * The shares the joined hubs publish, as the system's Files shows them: one root per share,
 * opened with the login given on the Files screen. A server that does not answer lists as the
 * error `share_unreachable` rather than waiting.
 */
class FilesDocumentsProvider : DocumentsProvider() {
    private val handler by lazy { Handler(HandlerThread("shares").apply { start() }.looper) }

    private val app: NeutrinoApplication
        get() = requireNotNull(context).applicationContext as NeutrinoApplication

    override fun onCreate(): Boolean = true

    override fun queryRoots(projection: Array<out String>?): Cursor {
        val cursor = MatrixCursor(projection ?: ROOT_COLUMNS)
        val reconnecting = words().word("ui.share_reconnecting")
        for (root in app.shareRoots.value) {
            cursor.newRow()
                .add(Root.COLUMN_ROOT_ID, root.key)
                .add(Root.COLUMN_DOCUMENT_ID, ShareDocumentId(root.key, "").encoded)
                .add(Root.COLUMN_TITLE, root.title)
                .add(Root.COLUMN_SUMMARY, if (root.isReconnecting) "${root.summary} · $reconnecting" else root.summary)
                .add(Root.COLUMN_FLAGS, Root.FLAG_SUPPORTS_CREATE or Root.FLAG_SUPPORTS_IS_CHILD)
                .add(Root.COLUMN_ICON, R.mipmap.ic_launcher)
        }
        return cursor
    }

    override fun queryDocument(documentId: String, projection: Array<out String>?): Cursor {
        val cursor = MatrixCursor(projection ?: DOCUMENT_COLUMNS)
        val document = ShareDocumentId.decode(documentId)
        val (root, login) = resolve(document) ?: return cursor.also { addFolder(it, document, "") }
        try {
            addRow(cursor, document, app.shares.stat(root, login, document))
        } catch (error: IOException) {
            addFolder(cursor, document, if (document.path.isEmpty()) root.title else document.name)
            cursor.extras = errorExtras(error, root)
        }
        return cursor
    }

    override fun queryChildDocuments(
        parentDocumentId: String,
        projection: Array<out String>?,
        sortOrder: String?,
    ): Cursor {
        val cursor = MatrixCursor(projection ?: DOCUMENT_COLUMNS)
        val parent = ShareDocumentId.decode(parentDocumentId)
        val resolved = resolve(parent)
        if (resolved == null) {
            cursor.extras =
                Bundle().apply {
                    putString(android.provider.DocumentsContract.EXTRA_ERROR, words().word("ui.share_login_needed"))
                }
            return cursor
        }
        val (root, login) = resolved
        try {
            for (entry in app.shares.list(root, login, parent)) addRow(cursor, parent.child(entry.name), entry)
        } catch (error: IOException) {
            cursor.extras = errorExtras(error, root)
        }
        return cursor
    }

    override fun openDocument(documentId: String, mode: String, signal: CancellationSignal?): ParcelFileDescriptor {
        val document = ShareDocumentId.decode(documentId)
        val (root, login) = resolve(document) ?: throw FileNotFoundException(words().word("ui.share_login_needed"))
        val file = try {
            app.shares.open(root, login, document, ShareOpenMode.parse(mode))
        } catch (error: IllegalArgumentException) {
            throw FileNotFoundException(error.message)
        } catch (error: IOException) {
            throw FileNotFoundException(wordOf(error))
        }
        val size = file.size
        val storage = requireNotNull(context).getSystemService(StorageManager::class.java)
        return storage.openProxyFileDescriptor(
            ParcelFileDescriptor.parseMode(mode),
            object : ProxyFileDescriptorCallback() {
                override fun onGetSize(): Long = size

                override fun onRead(offset: Long, count: Int, data: ByteArray): Int = io {
                    file.read(offset, data, count).coerceAtLeast(0)
                }

                override fun onWrite(offset: Long, count: Int, data: ByteArray): Int = io {
                    file.write(offset, data, count)
                    count
                }

                override fun onFsync() = Unit

                override fun onRelease() = file.close()
            },
            handler,
        )
    }

    override fun createDocument(parentDocumentId: String, mimeType: String, displayName: String): String {
        val parent = ShareDocumentId.decode(parentDocumentId)
        val (root, login) = resolve(parent) ?: throw FileNotFoundException(words().word("ui.share_login_needed"))
        val isDirectory = mimeType == Document.MIME_TYPE_DIR
        try {
            return app.shares.create(root, login, parent.child(displayName), isDirectory).encoded
        } catch (error: IOException) {
            throw FileNotFoundException(wordOf(error))
        }
    }

    override fun deleteDocument(documentId: String) {
        val document = ShareDocumentId.decode(documentId)
        val (root, login) = resolve(document) ?: throw FileNotFoundException(words().word("ui.share_login_needed"))
        try {
            app.shares.delete(root, login, document)
        } catch (error: IOException) {
            throw FileNotFoundException(wordOf(error))
        }
    }

    override fun isChildDocument(parentDocumentId: String, documentId: String): Boolean {
        val parent = ShareDocumentId.decode(parentDocumentId)
        val document = ShareDocumentId.decode(documentId)
        val isInside = parent.path.isEmpty() || document.path.startsWith(parent.path + "/")
        return parent.rootKey == document.rootKey && isInside
    }

    private fun resolve(document: ShareDocumentId): Pair<ShareRoot, ShareLogin>? {
        val root = app.shareRoots.value.firstOrNull { it.key == document.rootKey } ?: return null
        val login = app.shareLogins.get(root.key) ?: return null
        return root to login
    }

    private fun addRow(cursor: MatrixCursor, document: ShareDocumentId, entry: ShareEntry) {
        if (entry.isDirectory) {
            addFolder(cursor, document, entry.name)
            return
        }
        val extension = entry.name.substringAfterLast('.', "").lowercase()
        val type = MimeTypeMap.getSingleton().getMimeTypeFromExtension(extension) ?: "application/octet-stream"
        cursor.newRow()
            .add(Document.COLUMN_DOCUMENT_ID, document.encoded)
            .add(Document.COLUMN_DISPLAY_NAME, entry.name)
            .add(Document.COLUMN_MIME_TYPE, type)
            .add(Document.COLUMN_SIZE, entry.size)
            .add(Document.COLUMN_LAST_MODIFIED, entry.modifiedMillis)
            .add(Document.COLUMN_FLAGS, Document.FLAG_SUPPORTS_WRITE or Document.FLAG_SUPPORTS_DELETE)
    }

    private fun addFolder(cursor: MatrixCursor, document: ShareDocumentId, name: String) {
        cursor.newRow()
            .add(Document.COLUMN_DOCUMENT_ID, document.encoded)
            .add(Document.COLUMN_DISPLAY_NAME, name)
            .add(Document.COLUMN_MIME_TYPE, Document.MIME_TYPE_DIR)
            .add(Document.COLUMN_FLAGS, Document.FLAG_DIR_SUPPORTS_CREATE or Document.FLAG_SUPPORTS_DELETE)
    }

    private fun errorExtras(error: IOException, root: ShareRoot): Bundle {
        if (error is ShareRefusedException && error.code == "share_login_rejected") app.shareLogins.forget(root.key)
        return Bundle().apply { putString(android.provider.DocumentsContract.EXTRA_ERROR, wordOf(error)) }
    }

    private fun wordOf(error: IOException): String = when (error) {
        is ShareRefusedException -> words().refusal(error.code)

        is ShareUnreachableException -> words().refusal("share_unreachable")

        is ConnectRefusedException -> words().refusal(
            error.code,
            ChannelResult.Refused(error.code, error.params).wordParams,
        )

        else -> error.message.orEmpty()
    }

    private fun words(): WordCatalog =
        WordCatalog.load(requireNotNull(context).assets, app.settingsStore.settings.value.language)

    private fun io(action: () -> Int): Int = try {
        action()
    } catch (_: IOException) {
        throw ErrnoException("smb", OsConstants.EIO)
    } catch (_: RuntimeException) {
        throw ErrnoException("smb", OsConstants.EIO)
    }

    private companion object {
        val ROOT_COLUMNS = arrayOf(
            Root.COLUMN_ROOT_ID,
            Root.COLUMN_DOCUMENT_ID,
            Root.COLUMN_TITLE,
            Root.COLUMN_SUMMARY,
            Root.COLUMN_FLAGS,
            Root.COLUMN_ICON,
        )
        val DOCUMENT_COLUMNS = arrayOf(
            Document.COLUMN_DOCUMENT_ID,
            Document.COLUMN_DISPLAY_NAME,
            Document.COLUMN_MIME_TYPE,
            Document.COLUMN_SIZE,
            Document.COLUMN_LAST_MODIFIED,
            Document.COLUMN_FLAGS,
        )
    }
}

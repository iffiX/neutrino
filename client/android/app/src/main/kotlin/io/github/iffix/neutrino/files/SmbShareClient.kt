package io.github.iffix.neutrino.files

import com.hierynomus.msdtyp.AccessMask
import com.hierynomus.mserref.NtStatus
import com.hierynomus.msfscc.FileAttributes
import com.hierynomus.mssmb2.SMB2CreateDisposition
import com.hierynomus.mssmb2.SMB2Packet
import com.hierynomus.mssmb2.SMB2ShareAccess
import com.hierynomus.mssmb2.SMBApiException
import com.hierynomus.mssmb2.messages.SMB2Echo
import com.hierynomus.smbj.SMBClient
import com.hierynomus.smbj.SmbConfig
import com.hierynomus.smbj.auth.AuthenticationContext
import com.hierynomus.smbj.common.SMBRuntimeException
import com.hierynomus.smbj.connection.Connection
import com.hierynomus.smbj.share.DiskShare
import com.hierynomus.smbj.share.File
import io.github.iffix.neutrino.CLIENT_SHARE_NAME_ATTEMPTS
import io.github.iffix.neutrino.ConnectRefusedException
import io.github.iffix.neutrino.ShareRefusedException
import io.github.iffix.neutrino.ShareUnreachableException
import io.github.iffix.neutrino.channel.ChannelResult
import io.github.iffix.neutrino.channel.ChannelStream
import java.io.Closeable
import java.io.IOException
import java.util.EnumSet
import java.util.concurrent.TimeUnit

/**
 * SMB over smbj. Browsing runs on one held connection per root, and every file the system's
 * Files opens gets a connection of its own, so a long copy and a listing never close each other.
 * Every connection is a `connect` stream to the root's hub naming its `file` entry, so no
 * connection dials the share's own address. Each request is bounded long so a slow transfer is
 * not taken for a dead server. Signing follows the server; SMB 2.0.2 to 3.1.1 are offered.
 *
 * @param ioTimeoutSeconds How long one request, a read or a write may take.
 * @param idleProbeSeconds How long a held connection may sit unused before it is probed.
 * @param probeTimeoutSeconds How long the probe of a held connection may take.
 * @param streams Opens one `connect` stream for a root's connection.
 */
class SmbShareClient(
    private val ioTimeoutSeconds: Long,
    idleProbeSeconds: Long,
    private val probeTimeoutSeconds: Long,
    private val streams: (ShareRoot) -> ChannelResult<ChannelStream>,
) {
    private val pool = ShareConnectionPool(
        open = ::connect,
        probe = ::answers,
        close = SmbLink::close,
        isLost = ::isLost,
        idleProbeMillis = idleProbeSeconds * 1000,
    )

    /**
     * The files and folders of one folder.
     *
     * @param root The share.
     * @param login Its login.
     * @param document The folder.
     * @return Its entries, without `.` and `..`.
     * @throws ShareUnreachableException When the server cannot be reached.
     * @throws ConnectRefusedException When the hub refuses the connection to the share.
     * @throws ShareRefusedException When the server refuses the login, the access or the name.
     */
    fun list(root: ShareRoot, login: ShareLogin, document: ShareDocumentId): List<ShareEntry> =
        call(root, login) { share ->
            share.list(document.smbPath).filter { it.fileName != "." && it.fileName != ".." }.map {
                ShareEntry(
                    name = it.fileName,
                    isDirectory = it.fileAttributes and FileAttributes.FILE_ATTRIBUTE_DIRECTORY.value != 0L,
                    size = it.endOfFile,
                    modifiedMillis = it.lastWriteTime.toEpochMillis(),
                )
            }
        }

    /**
     * One file's or folder's own entry.
     *
     * @param root The share.
     * @param login Its login.
     * @param document The file or folder; the share itself for an empty path.
     * @return Its entry.
     * @throws ShareUnreachableException When the server cannot be reached.
     * @throws ConnectRefusedException When the hub refuses the connection to the share.
     * @throws ShareRefusedException When the server refuses.
     */
    fun stat(root: ShareRoot, login: ShareLogin, document: ShareDocumentId): ShareEntry = call(root, login) { share ->
        if (document.path.isEmpty()) return@call ShareEntry(root.title, true, 0, 0)
        val info = share.getFileInformation(document.smbPath)
        ShareEntry(
            name = document.name,
            isDirectory = info.standardInformation.isDirectory,
            size = info.standardInformation.endOfFile,
            modifiedMillis = info.basicInformation.lastWriteTime.toEpochMillis(),
        )
    }

    /**
     * Open a file to read or to write, on a connection of its own; a read or a write that fails
     * opens it again once.
     *
     * @param root The share.
     * @param login Its login.
     * @param document The file.
     * @param mode How it is opened, which may write it and empty it first.
     * @return The open file, closed by the caller.
     * @throws ShareUnreachableException When the server cannot be reached.
     * @throws ConnectRefusedException When the hub refuses the connection to the share.
     * @throws ShareRefusedException When the server refuses.
     */
    fun open(root: ShareRoot, login: ShareLogin, document: ShareDocumentId, mode: ShareOpenMode): ShareFile =
        translated(root) { ShareFile { isAgain -> openLink(root, login, document, mode, isAgain) } }

    /**
     * Make an empty file or a folder under the first free name, never touching one that exists.
     *
     * @param root The share.
     * @param login Its login.
     * @param document The name asked for.
     * @param isDirectory Whether a folder is made.
     * @return The document made, numbered when the name asked for was taken.
     * @throws ShareUnreachableException When the server cannot be reached.
     * @throws ConnectRefusedException When the hub refuses the connection to the share.
     * @throws ShareRefusedException When the server refuses.
     * @throws java.nio.file.FileAlreadyExistsException When every name tried is taken.
     */
    fun create(root: ShareRoot, login: ShareLogin, document: ShareDocumentId, isDirectory: Boolean): ShareDocumentId =
        call(root, login) { share ->
            document.makeFree(isDirectory, CLIENT_SHARE_NAME_ATTEMPTS) { candidate ->
                try {
                    if (isDirectory) {
                        share.mkdir(candidate.smbPath)
                    } else {
                        share.openFile(
                            candidate.smbPath,
                            EnumSet.of(AccessMask.GENERIC_WRITE),
                            null,
                            SMB2ShareAccess.ALL,
                            SMB2CreateDisposition.FILE_CREATE,
                            null,
                        ).close()
                    }
                    true
                } catch (error: SMBApiException) {
                    if (error.status != NtStatus.STATUS_OBJECT_NAME_COLLISION) throw error
                    false
                }
            }
        }

    /**
     * Delete a file, or a folder with everything in it.
     *
     * @param root The share.
     * @param login Its login.
     * @param document The file or folder.
     * @throws ShareUnreachableException When the server cannot be reached.
     * @throws ConnectRefusedException When the hub refuses the connection to the share.
     * @throws ShareRefusedException When the server refuses.
     */
    fun delete(root: ShareRoot, login: ShareLogin, document: ShareDocumentId) = call(root, login) { share ->
        if (share.folderExists(document.smbPath)) share.rmdir(document.smbPath, true) else share.rm(document.smbPath)
    }

    /**
     * Close a share's connection, as after its login changed.
     *
     * @param rootKey The share's root id.
     */
    fun drop(rootKey: String) = pool.drop(rootKey)

    /** The app came back to the foreground: each held connection is probed once before its next request. */
    fun markStale() = pool.markStale()

    private fun <T> call(root: ShareRoot, login: ShareLogin, action: (DiskShare) -> T): T =
        translated(root) { pool.call(root, login) { link -> action(link.share) } }

    private fun <T> translated(root: ShareRoot, action: () -> T): T = try {
        action()
    } catch (error: SMBApiException) {
        throw refusalOf(error)
    } catch (error: ShareRefusedException) {
        throw error
    } catch (error: ShareUnreachableException) {
        throw error
    } catch (error: IOException) {
        throw refusedOf(error) ?: ShareUnreachableException("${root.host} does not answer", error)
    } catch (error: SMBRuntimeException) {
        throw refusedOf(error) ?: ShareUnreachableException("${root.host} does not answer", error)
    }

    private fun refusedOf(error: Throwable): ConnectRefusedException? =
        generateSequence(error) { it.cause }.filterIsInstance<ConnectRefusedException>().firstOrNull()

    private fun connect(root: ShareRoot, login: ShareLogin): SmbLink {
        val sockets = ShareSocketFactory { streams(root) }
        val config = SmbConfig.builder()
            .withTimeout(ioTimeoutSeconds, TimeUnit.SECONDS)
            .withSoTimeout(ioTimeoutSeconds, TimeUnit.SECONDS)
            .withSocketFactory(sockets)
            .build()
        val client = SMBClient(config)
        try {
            val connection = client.connect(root.host)
            val session = connection.authenticate(AuthenticationContext(login.user, login.password.toCharArray(), ""))
            val share = session.connectShare(root.share) as? DiskShare
                ?: throw ShareRefusedException("share_not_found", "${root.share} is not a disk share")
            return SmbLink(client, connection, share)
        } catch (error: Exception) {
            client.close()
            throw sockets.refusal?.let { ConnectRefusedException(it.code, it.params) } ?: error
        }
    }

    private fun openLink(
        root: ShareRoot,
        login: ShareLogin,
        document: ShareDocumentId,
        mode: ShareOpenMode,
        isAgain: Boolean,
    ): ShareFileLink {
        val link = connect(root, login)
        try {
            val isEmptied = mode.isTruncate && !isAgain
            val disposition = when {
                !mode.isWrite -> SMB2CreateDisposition.FILE_OPEN
                isEmptied -> SMB2CreateDisposition.FILE_OVERWRITE_IF
                else -> SMB2CreateDisposition.FILE_OPEN_IF
            }
            val access = EnumSet.of(AccessMask.FILE_READ_ATTRIBUTES)
            if (mode.isRead) access += AccessMask.GENERIC_READ
            if (mode.isWrite) access += AccessMask.GENERIC_WRITE
            val file = link.share.openFile(document.smbPath, access, null, SMB2ShareAccess.ALL, disposition, null)
            return SmbFileLink(link, file, if (isEmptied) 0L else file.fileInformation.standardInformation.endOfFile)
        } catch (error: Exception) {
            link.close()
            throw error
        }
    }

    private fun answers(link: SmbLink): Boolean = try {
        val connection = link.connection
        connection.isConnected &&
            connection.send<SMB2Packet>(SMB2Echo(connection.negotiatedProtocol.dialect))
                .get(probeTimeoutSeconds, TimeUnit.SECONDS) != null
    } catch (_: Exception) {
        false
    }

    private fun isLost(error: Exception): Boolean = when (error) {
        is ShareRefusedException -> false

        is SMBApiException ->
            error.status == NtStatus.STATUS_NETWORK_NAME_DELETED ||
                error.status == NtStatus.STATUS_USER_SESSION_DELETED

        is SMBRuntimeException, is IOException -> true

        else -> false
    }

    private fun refusalOf(error: SMBApiException): IOException = when (error.status) {
        NtStatus.STATUS_LOGON_FAILURE,
        NtStatus.STATUS_ACCOUNT_DISABLED,
        NtStatus.STATUS_PASSWORD_EXPIRED,
        NtStatus.STATUS_LOGON_TYPE_NOT_GRANTED,
        ->
            ShareRefusedException("share_login_rejected", error.message.orEmpty())

        NtStatus.STATUS_ACCESS_DENIED -> ShareRefusedException("share_access_denied", error.message.orEmpty())

        NtStatus.STATUS_BAD_NETWORK_NAME,
        NtStatus.STATUS_OBJECT_NAME_NOT_FOUND,
        NtStatus.STATUS_OBJECT_PATH_NOT_FOUND,
        ->
            ShareRefusedException("share_not_found", error.message.orEmpty())

        else -> ShareUnreachableException(error.message.orEmpty(), error)
    }

    private class SmbLink(val client: SMBClient, val connection: Connection, val share: DiskShare) : Closeable {
        override fun close() {
            try {
                client.close()
            } catch (_: Exception) {
                // The connection was already gone.
            }
        }
    }

    private class SmbFileLink(private val link: SmbLink, private val file: File, override val size: Long) :
        ShareFileLink {
        override fun read(offset: Long, data: ByteArray, count: Int): Int = file.read(data, offset, 0, count)

        override fun write(offset: Long, data: ByteArray, count: Int) {
            file.write(data, offset, 0, count)
        }

        override fun close() {
            try {
                file.close()
            } finally {
                link.close()
            }
        }
    }
}

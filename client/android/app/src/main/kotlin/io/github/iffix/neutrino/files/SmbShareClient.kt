package io.github.iffix.neutrino.files

import com.hierynomus.msdtyp.AccessMask
import com.hierynomus.mserref.NtStatus
import com.hierynomus.msfscc.FileAttributes
import com.hierynomus.mssmb2.SMB2CreateDisposition
import com.hierynomus.mssmb2.SMB2ShareAccess
import com.hierynomus.mssmb2.SMBApiException
import com.hierynomus.smbj.SMBClient
import com.hierynomus.smbj.SmbConfig
import com.hierynomus.smbj.auth.AuthenticationContext
import com.hierynomus.smbj.connection.Connection
import com.hierynomus.smbj.share.DiskShare
import com.hierynomus.smbj.share.File
import io.github.iffix.neutrino.ShareRefusedException
import io.github.iffix.neutrino.ShareUnreachableException
import java.io.IOException
import java.net.InetAddress
import java.net.InetSocketAddress
import java.net.Socket
import java.util.EnumSet
import java.util.concurrent.TimeUnit
import javax.net.SocketFactory

/**
 * SMB over smbj, one open share per root, with every wait bounded so an unreachable server is an
 * answer, not a hang. Signing follows the server; SMB 2.0.2 to 3.1.1 are offered.
 *
 * @param timeoutSeconds How long connecting and each request may take.
 */
class SmbShareClient(private val timeoutSeconds: Long) {
    private val client = SMBClient(
        SmbConfig.builder()
            .withTimeout(timeoutSeconds, TimeUnit.SECONDS)
            .withSoTimeout(timeoutSeconds, TimeUnit.SECONDS)
            .withSocketFactory(BoundedSocketFactory((timeoutSeconds * 1000).toInt()))
            .build(),
    )
    private val shares = mutableMapOf<String, Pair<Connection, DiskShare>>()

    /**
     * The files and folders of one folder.
     *
     * @param root The share.
     * @param login Its login.
     * @param document The folder.
     * @return Its entries, without `.` and `..`.
     * @throws ShareUnreachableException When the server cannot be reached.
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
     * Open a file to read or to write.
     *
     * @param root The share.
     * @param login Its login.
     * @param document The file.
     * @param isWrite Whether it is opened to write, made when missing and emptied first.
     * @return The open file, closed by the caller.
     * @throws ShareUnreachableException When the server cannot be reached.
     * @throws ShareRefusedException When the server refuses.
     */
    fun open(root: ShareRoot, login: ShareLogin, document: ShareDocumentId, isWrite: Boolean): File =
        call(root, login) { share ->
            share.openFile(
                document.smbPath,
                EnumSet.of(if (isWrite) AccessMask.GENERIC_WRITE else AccessMask.GENERIC_READ),
                null,
                SMB2ShareAccess.ALL,
                if (isWrite) SMB2CreateDisposition.FILE_OVERWRITE_IF else SMB2CreateDisposition.FILE_OPEN,
                null,
            )
        }

    /**
     * Make a folder.
     *
     * @param root The share.
     * @param login Its login.
     * @param document The new folder.
     * @throws ShareUnreachableException When the server cannot be reached.
     * @throws ShareRefusedException When the server refuses.
     */
    fun mkdir(root: ShareRoot, login: ShareLogin, document: ShareDocumentId) =
        call(root, login) { it.mkdir(document.smbPath) }

    /**
     * Delete a file, or a folder with everything in it.
     *
     * @param root The share.
     * @param login Its login.
     * @param document The file or folder.
     * @throws ShareUnreachableException When the server cannot be reached.
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
    fun drop(rootKey: String) {
        val (connection, _) = synchronized(shares) { shares.remove(rootKey) } ?: return
        try {
            connection.close()
        } catch (_: IOException) {
            // The connection was already gone.
        }
    }

    private fun <T> call(root: ShareRoot, login: ShareLogin, action: (DiskShare) -> T): T {
        try {
            return action(share(root, login))
        } catch (error: SMBApiException) {
            if (error.status == NtStatus.STATUS_NETWORK_NAME_DELETED ||
                error.status == NtStatus.STATUS_USER_SESSION_DELETED
            ) {
                drop(root.key)
                return action(share(root, login))
            }
            throw refusalOf(error)
        } catch (error: IOException) {
            drop(root.key)
            throw error as? ShareRefusedException ?: error as? ShareUnreachableException
                ?: ShareUnreachableException("${root.host} does not answer", error)
        }
    }

    private fun share(root: ShareRoot, login: ShareLogin): DiskShare {
        synchronized(shares) { shares[root.key]?.second?.takeIf { it.isConnected } }?.let { return it }
        try {
            val connection = client.connect(root.host)
            val session = connection.authenticate(AuthenticationContext(login.user, login.password.toCharArray(), ""))
            val share = session.connectShare(root.share) as? DiskShare
                ?: throw ShareRefusedException("share_not_found", "${root.share} is not a disk share")
            synchronized(shares) { shares[root.key] = connection to share }
            return share
        } catch (error: SMBApiException) {
            throw refusalOf(error)
        } catch (error: IOException) {
            throw error as? ShareRefusedException ?: ShareUnreachableException("${root.host} does not answer", error)
        }
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

    private class BoundedSocketFactory(private val timeoutMillis: Int) : SocketFactory() {
        override fun createSocket(): Socket = Bounded(timeoutMillis)

        override fun createSocket(host: String, port: Int): Socket =
            Bounded(timeoutMillis).apply { connect(InetSocketAddress(host, port)) }

        override fun createSocket(host: String, port: Int, localHost: InetAddress, localPort: Int): Socket =
            createSocket(host, port)

        override fun createSocket(host: InetAddress, port: Int): Socket =
            Bounded(timeoutMillis).apply { connect(InetSocketAddress(host, port)) }

        override fun createSocket(address: InetAddress, port: Int, localAddress: InetAddress, localPort: Int): Socket =
            createSocket(address, port)
    }

    private class Bounded(private val timeoutMillis: Int) : Socket() {
        override fun connect(endpoint: java.net.SocketAddress) = connect(endpoint, timeoutMillis)
    }
}

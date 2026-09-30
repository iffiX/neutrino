package io.github.iffix.neutrino.binding

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import io.github.iffix.neutrino.SEAL_KEYSTORE
import io.github.iffix.neutrino.SEAL_KEY_BITS
import io.github.iffix.neutrino.SEAL_NONCE_BYTES
import io.github.iffix.neutrino.SEAL_TAG_BITS
import io.github.iffix.neutrino.SEAL_TRANSFORMATION
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * Seals with AES-256-GCM under a key the Android Keystore holds and never exports.
 *
 * A sealed value is the 12-byte nonce, then the ciphertext with its tag.
 *
 * @param alias The Keystore alias of the key, made on first use.
 */
class KeystoreSecretSealer(private val alias: String) : SecretSealer {
    override fun seal(plain: ByteArray): ByteArray {
        val cipher = Cipher.getInstance(SEAL_TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, key())
        return cipher.iv + cipher.doFinal(plain)
    }

    override fun open(sealed: ByteArray): ByteArray {
        val cipher = Cipher.getInstance(SEAL_TRANSFORMATION)
        cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(SEAL_TAG_BITS, sealed, 0, SEAL_NONCE_BYTES))
        return cipher.doFinal(sealed, SEAL_NONCE_BYTES, sealed.size - SEAL_NONCE_BYTES)
    }

    private fun key(): SecretKey {
        val store = KeyStore.getInstance(SEAL_KEYSTORE).apply { load(null) }
        (store.getEntry(alias, null) as? KeyStore.SecretKeyEntry)?.let { return it.secretKey }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, SEAL_KEYSTORE)
        generator.init(
            KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(SEAL_KEY_BITS)
                .build(),
        )
        return generator.generateKey()
    }
}

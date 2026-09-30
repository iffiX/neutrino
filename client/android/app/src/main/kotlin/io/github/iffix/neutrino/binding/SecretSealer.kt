package io.github.iffix.neutrino.binding

/** Seals bytes under a key that never leaves the phone, and opens what it sealed. */
interface SecretSealer {
    /**
     * Seal bytes.
     *
     * @param plain What to seal.
     * @return The sealed bytes.
     * @throws java.security.GeneralSecurityException When the key cannot seal.
     */
    fun seal(plain: ByteArray): ByteArray

    /**
     * Open what [seal] sealed.
     *
     * @param sealed The sealed bytes.
     * @return The plain bytes.
     * @throws java.security.GeneralSecurityException When the bytes were not sealed by this key.
     */
    fun open(sealed: ByteArray): ByteArray
}

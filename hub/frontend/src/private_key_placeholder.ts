/**
 * The placeholder shown in every "paste a private key" box.
 *
 * Deliberately a template, not realistic key material: an earlier version
 * showed convincing-looking base64, which read as though a stored key were
 * being displayed. This makes it unmistakable that the box is empty and what
 * belongs in it.
 */
export const PRIVATE_KEY_PLACEHOLDER = `-----BEGIN OPENSSH PRIVATE KEY-----
paste the whole private key here, including the BEGIN and END lines
-----END OPENSSH PRIVATE KEY-----

The private key file, not the .pub. Also accepts
'-----BEGIN RSA PRIVATE KEY-----' and '-----BEGIN EC PRIVATE KEY-----'.`;

package handshake

// cacophonyVector is the Noise_IKpsk2_25519_ChaChaPoly_BLAKE2s vector of
// flynn/noise v1.1.0's vectors.txt, the cacophony vector with an empty
// prologue, kept here beside the package.
var cacophonyVector = vector{
	InitStatic:     "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f",                                                                                                                                 // scan: allow
	RespStatic:     "0102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f20",                                                                                                                                 // scan: allow
	InitEphemeral:  "202122232425262728292a2b2c2d2e2f303132333435363738393a3b3c3d3e3f",                                                                                                                                 // scan: allow
	RespEphemeral:  "4142434445464748494a4b4c4d4e4f505152535455565758595a5b5c5d5e5f60",                                                                                                                                 // scan: allow
	PresharedKey:   "2176657279736563726574766572797365637265747665727973656372657421",                                                                                                                                 // scan: allow
	Msg0Payload:    "",                                                                                                                                                                                                 // scan: allow
	Msg0Ciphertext: "358072d6365880d1aeea329adf9121383851ed21a28e3b75e965d0d2cd166254d06f15f78ad0914d9715147bb5a5004b27345a838bab4aa8bc5f144afc2cf4cca972105ba526e8c92b759e028200e766f827aa12a04ecbc0bdcd9e574e007945", // scan: allow
	Msg1Payload:    "",                                                                                                                                                                                                 // scan: allow
	Msg1Ciphertext: "64b101b1d0be5a8704bd078f9895001fc03e8e9f9522f188dd128d9846d484668c46d966ca4fe339f9e47fd25f68de8a",                                                                                                 // scan: allow
	Msg2Payload:    "79656c6c6f777375626d6172696e65",                                                                                                                                                                   // scan: allow
	Msg2Ciphertext: "6013ea114b4c4884afb82bf029f72f924bd8a32c487a15a1cef4855ba234be",                                                                                                                                   // scan: allow
	Msg3Payload:    "7375626d6172696e6579656c6c6f77",                                                                                                                                                                   // scan: allow
	Msg3Ciphertext: "8a2e7119635e41a35b7e64e0adac5483b66b1a9827895124ea07d58440b654",                                                                                                                                   // scan: allow
}

// paddedVector is message 1 and message 2 of the cacophony keys under the
// channel's prologue, message 1 carrying a payload's JSON and 64 bytes of
// 0xa5 padding and message 2 64 bytes of 0x5a padding. It was made on
// 2026-10-28 when the padding was added.
var paddedVector = struct {
	Payload      string
	Padding1     byte
	Padding2     byte
	PaddingBytes int
	Message1     string
	Message2     string
}{
	Payload:      `{"protocol":4,"role":"agent","is_join":false,"time":1761600000000000000}`,
	Padding1:     0xa5,
	Padding2:     0x5a,
	PaddingBytes: 64,
	Message1:     "358072d6365880d1aeea329adf9121383851ed21a28e3b75e965d0d2cd166254d06f15f78ad0914d9715147bb5a5004b27345a838bab4aa8bc5f144afc2cf4cc142fdcfd78db6728d82683ff8e94a852657a74be5f83b479ffba58cf336b4203db897fba7b18229f65d3a4ba8adfb3187bba9176cabc81cd87810d2675ff708bbd4a99b94dafbdb4ec10798d9b7c4634d6acaee934605f25b01e29060e87d6a37ccb50a49703cfb98ae6e8d627b213004ca628fc17691e5c80aa3569cb44b9f95c1d89017846426bb6f7e553cea7849c1aab8e093d9c2840e6ed4b2141c87477ead86501bccfb226", // scan: allow
	Message2:     "64b101b1d0be5a8704bd078f9895001fc03e8e9f9522f188dd128d9846d4846638b1403de2ba531601d9845fb9643872978fdc7ce1f9d8793f1f38a7b057e10cd5b058d28016dc307af498c0bba9a89b533f0681d31a63e6294c80bb3a362b12b5de7fcc845958860bd46e412f846213",                                                                                                                                                                                                                                                 // scan: allow
}

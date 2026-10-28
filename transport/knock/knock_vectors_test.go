package knock

// knockVectors are the mac vectors of the knock tests, computed once with
// BLAKE2s over fixed inputs and kept here beside the package. They were made
// again on 2026-10-27 when the eight-byte header replaced the version byte.
var knockVectors = vectors{
	HubPublic: "8520f0098930a754748b7ddcb43ef75a0dbf3a0d26381af4eba4a98eaa9b4e6a",                                                                                                                                                                                                           // scan: allow
	Magic:     "736fbc12",                                                                                                                                                                                                                                                                   // scan: allow
	Message1:  "358072d6365880d1aeea329adf9121383851ed21a28e3b75e965d0d2cd166254d06f15f78ad0914d9715147bb5a5004b27345a838bab4aa8bc5f144afc2cf4cca972105ba526e8c92b759e028200e766f827aa12a04ecbc0bdcd9e",                                                                                     // scan: allow
	Mac1Key:   "0ec72453412f9befa2f799ea837d0b88429321711dd01f9025163123bd1905be",                                                                                                                                                                                                           // scan: allow
	Mac1:      "50bdc6308ccaa14e761993eadab604de",                                                                                                                                                                                                                                           // scan: allow
	Cookie:    "000102030405060708090a0b0c0d0e0f",                                                                                                                                                                                                                                           // scan: allow
	Mac2:      "6b4613787913598b89fe9563748ed1ca",                                                                                                                                                                                                                                           // scan: allow
	Knock:     "736fbc1200040100005b358072d6365880d1aeea329adf9121383851ed21a28e3b75e965d0d2cd166254d06f15f78ad0914d9715147bb5a5004b27345a838bab4aa8bc5f144afc2cf4cca972105ba526e8c92b759e028200e766f827aa12a04ecbc0bdcd9e50bdc6308ccaa14e761993eadab604de6b4613787913598b89fe9563748ed1ca", // scan: allow
}

// paddedKnockVector is the knock over the padded message 1 of the handshake
// package's paddedVector, under knockVectors' hub key and cookie: the
// largest knock an agent's payload makes, 274 bytes. It was made on
// 2026-10-28 when the padding was added.
var paddedKnockVector = struct {
	Message1 string
	Knock    string
}{
	Message1: "358072d6365880d1aeea329adf9121383851ed21a28e3b75e965d0d2cd166254d06f15f78ad0914d9715147bb5a5004b27345a838bab4aa8bc5f144afc2cf4cc142fdcfd78db6728d82683ff8e94a852657a74be5f83b479ffba58cf336b4203db897fba7b18229f65d3a4ba8adfb3187bba9176cabc81cd87810d2675ff708bbd4a99b94dafbdb4ec10798d9b7c4634d6acaee934605f25b01e29060e87d6a37ccb50a49703cfb98ae6e8d627b213004ca628fc17691e5c80aa3569cb44b9f95c1d89017846426bb6f7e553cea7849c1aab8e093d9c2840e6ed4b2141c87477ead86501bccfb226",                                                                                     // scan: allow
	Knock:    "736fbc120004010000e8358072d6365880d1aeea329adf9121383851ed21a28e3b75e965d0d2cd166254d06f15f78ad0914d9715147bb5a5004b27345a838bab4aa8bc5f144afc2cf4cc142fdcfd78db6728d82683ff8e94a852657a74be5f83b479ffba58cf336b4203db897fba7b18229f65d3a4ba8adfb3187bba9176cabc81cd87810d2675ff708bbd4a99b94dafbdb4ec10798d9b7c4634d6acaee934605f25b01e29060e87d6a37ccb50a49703cfb98ae6e8d627b213004ca628fc17691e5c80aa3569cb44b9f95c1d89017846426bb6f7e553cea7849c1aab8e093d9c2840e6ed4b2141c87477ead86501bccfb22648856c1b8813eb1f89dae6245fa04fbc47b9d3246285e0a1214fbd3f4cb5a9fb", // scan: allow
}

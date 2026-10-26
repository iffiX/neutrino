// Package knock is the first message a peer sends on the agent port and
// everything the hub judges before it spends a Diffie-Hellman on it: the
// knock's layout, mac1 under the hub's static public key, mac2 under a
// cookie, the cookie reply the hub writes under load, the replay window per
// static key, and the counts of unadmitted connections and handshakes in
// flight with their limits.
package knock

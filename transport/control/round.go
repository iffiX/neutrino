package control

import (
	"context"
	"time"

	"github.com/iffiX/neutrino/transport/session"
)

// candidate is one address of a round with its path.
type candidate struct {
	Address string `json:"address"`
	Path    string `json:"path"`
}

// roundResult is what a round ends with: a session, or the refusal that
// names why there is none.
type roundResult struct {
	session *PeerSession
	refusal *session.Refusal
}

// dialAtOnce is a round of an agent or a client: every candidate at once,
// each within DialTimeout from the round's start, an address refusing the
// connection dialled again every RedialInterval. The first handshake that
// completes wins and every other connection is closed before any hello. At a
// join, an answer under neither psk before the winner ends the round with
// hub_untrusted.
func dialAtOnce(ctx context.Context, candidates []candidate, settings dialSettings) roundResult {
	ctx, cancel := context.WithTimeout(ctx, session.DialTimeout)
	defer cancel()
	type outcome struct {
		session *PeerSession
		refusal *session.Refusal
		err     error
	}
	results := make(chan outcome, len(candidates))
	started := 0
	for _, c := range candidates {
		if _, err := session.ParseAddress(c.Address); err != nil {
			continue
		}
		started++
		go func(c candidate) {
			for {
				peer, refusal, err := connectSession(ctx, c.Address, c.Path, settings)
				if err != nil && isRefusedConnection(err) && ctx.Err() == nil {
					select {
					case <-ctx.Done():
					case <-time.After(session.RedialInterval):
						continue
					}
				}
				results <- outcome{session: peer, refusal: refusal, err: err}
				return
			}
		}(c)
	}
	var lastErr error
	isUntrustedSeen := false
	var winner *PeerSession
	var refusal *session.Refusal
	for i := 0; i < started; i++ {
		result := <-results
		switch {
		case result.session != nil:
			if winner == nil && refusal == nil {
				winner = result.session
				cancel()
			} else {
				result.session.Close()
			}
		case result.refusal != nil:
			if winner == nil && refusal == nil {
				refusal = result.refusal
				cancel()
			}
		case isUntrusted(result.err):
			isUntrustedSeen = true
			if settings.isJoin && winner == nil && refusal == nil {
				refusal = session.NewRefusal(session.CodeHubUntrusted, nil)
				cancel()
			}
		default:
			lastErr = result.err
		}
	}
	switch {
	case winner != nil:
		return roundResult{session: winner}
	case refusal != nil:
		return roundResult{refusal: refusal}
	case isUntrustedSeen:
		return roundResult{refusal: session.NewRefusal(session.CodeHubUntrusted, nil)}
	}
	return roundResult{refusal: hubUnreachable(lastErr)}
}

// candidatesOf is an agent's addresses as candidates with no path.
func candidatesOf(addresses []string) []candidate {
	candidates := make([]candidate, 0, len(addresses))
	for _, address := range addresses {
		candidates = append(candidates, candidate{Address: address})
	}
	return candidates
}

// isFinal reports whether a refusal ends the dialling until the next dial
// command.
func isFinal(refusal *session.Refusal) bool {
	return refusal.Code == session.CodeReplaced || refusal.Code == session.CodeBindingUnknown
}

// waitAfterRefusal is the wait before dialling again after the hub refused:
// RedialBackoffMax, or retry_after_s when the refusal names one.
func waitAfterRefusal(refusal *session.Refusal) time.Duration {
	if seconds, ok := refusal.Params["retry_after_s"].(float64); ok && seconds > 0 {
		return time.Duration(seconds * float64(time.Second))
	}
	return session.RedialBackoffMax
}

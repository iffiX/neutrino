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

// dialInOrder is an agent's round: each address in turn, RotateDelay apart,
// each within DialTimeout. It ends at the first session or the first refusal
// the hub said; an address answering under neither psk is skipped, and the
// round reports hub_untrusted when no other address won.
func dialInOrder(ctx context.Context, addresses []string, settings dialSettings) roundResult {
	var lastErr error
	isUntrustedSeen := false
	for i, address := range addresses {
		if i > 0 {
			select {
			case <-ctx.Done():
				return roundResult{refusal: hubUnreachable(ctx.Err())}
			case <-time.After(session.RotateDelay):
			}
		}
		if _, err := session.ParseAddress(address); err != nil {
			continue
		}
		peer, refusal, err := connectSession(ctx, address, "", settings)
		if err == nil && refusal == nil {
			return roundResult{session: peer}
		}
		if refusal != nil {
			return roundResult{refusal: refusal}
		}
		if isUntrusted(err) {
			if settings.isJoin {
				return roundResult{refusal: session.NewRefusal(session.CodeHubUntrusted, nil)}
			}
			isUntrustedSeen = true
			continue
		}
		lastErr = err
	}
	if isUntrustedSeen {
		return roundResult{refusal: session.NewRefusal(session.CodeHubUntrusted, nil)}
	}
	return roundResult{refusal: hubUnreachable(lastErr)}
}

// dialAtOnce is a client's round: every candidate at once, each within
// DialTimeout from the round's start, an address refusing the connection
// dialled again every RedialInterval. The first handshake that completes
// wins and every other connection is closed before any hello.
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

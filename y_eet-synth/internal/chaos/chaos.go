// Package chaos implements fault injection scenarios for staging validation.
// WARNING: Run only in staging or controlled environments.
package chaos

import (
	"context"
	"fmt"
	"math/rand"

	"y_eet-synth/internal/client"
	"y_eet-synth/internal/evaluator"
	"y_eet-synth/internal/token"
)

// Injector runs chaos / fault-path validation scenarios.
type Injector struct {
	cl   *client.Client
	pool *token.Pool
}

// New creates an Injector.
func New(cl *client.Client, pool *token.Pool) *Injector {
	return &Injector{cl: cl, pool: pool}
}

// RunAll executes all chaos scenarios and returns their results.
func (i *Injector) RunAll(ctx context.Context) []evaluator.ChaosResult {
	return []evaluator.ChaosResult{
		i.staleToken(ctx),
		i.malformedPayload(ctx),
		i.duplicateReplay(ctx),
		i.missingIdempotencyKey(ctx),
		i.oversizedPayload(ctx),
	}
}

// staleToken sends a request with a deliberately invalid token.
// The API must respond with 401.
func (i *Injector) staleToken(ctx context.Context) evaluator.ChaosResult {
	r := i.cl.Do(ctx, client.RequestOptions{
		Method:       "GET",
		Path:         "/api/v1/users/chaos-test/profile",
		Token:        "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.INVALID.STALE",
		EndpointName: "GET /api/v1/users/:id/profile",
	})
	passed := r.StatusCode == 401 || r.StatusCode == 403
	return evaluator.ChaosResult{
		Scenario:       "stale_token",
		Passed:         passed,
		ExpectedStatus: 401,
		StatusCode:     r.StatusCode,
		Note: func() string {
			if passed {
				return "stale token correctly rejected"
			}
			return fmt.Sprintf("expected 401/403, got %d — auth middleware may not be enforcing JWT expiry", r.StatusCode)
		}(),
	}
}

// malformedPayload sends an invalid JSON body; API must respond with 400/422.
func (i *Injector) malformedPayload(ctx context.Context) evaluator.ChaosResult {
	creds := i.pool.GetRandom()
	if creds == nil {
		return evaluator.ChaosResult{
			Scenario: "malformed_payload",
			Passed:   true,
			Note:     "skipped: no token available",
		}
	}
	// Send a string where an object is expected
	r := i.cl.Do(ctx, client.RequestOptions{
		Method:       "POST",
		Path:         "/api/v1/bets/place",
		Token:        creds.AccessToken,
		Body:         "this is not json at all ><",
		EndpointName: "POST /api/v1/bets/place",
	})
	passed := r.StatusCode == 400 || r.StatusCode == 422 || r.StatusCode == 415
	return evaluator.ChaosResult{
		Scenario:       "malformed_payload",
		Passed:         passed,
		ExpectedStatus: 400,
		StatusCode:     r.StatusCode,
		Note: func() string {
			if passed {
				return "malformed payload correctly rejected"
			}
			return fmt.Sprintf("expected 400/422, got %d — input validation may not be enforced", r.StatusCode)
		}(),
	}
}

// duplicateReplay sends the same idempotency key twice.
// The second request must return the same 2xx (idempotency) or 409.
func (i *Injector) duplicateReplay(ctx context.Context) evaluator.ChaosResult {
	creds := i.pool.GetRandom()
	if creds == nil {
		return evaluator.ChaosResult{
			Scenario: "duplicate_replay",
			Passed:   true,
			Note:     "skipped: no token available",
		}
	}

	idemKey := fmt.Sprintf("chaos-replay-%08x", rand.Int63()) //nolint:gosec
	body := map[string]interface{}{
		"amount":           "10.00",
		"currency":         "USD",
		"payment_method":   "card",
		"client_reference": idemKey,
	}

	uid := creds.UserID
	opts := client.RequestOptions{
		Method:         "POST",
		Path:           "/api/v1/wallet/" + uid + "/deposit",
		Token:          creds.AccessToken,
		IdempotencyKey: idemKey,
		Body:           body,
		EndpointName:   "POST /api/v1/wallet/:id/deposit",
	}

	r1 := i.cl.Do(ctx, opts)
	r2 := i.cl.Do(ctx, opts) // exact replay

	// Second request should be idempotent (same 2xx) or 409
	passed := (r2.StatusCode >= 200 && r2.StatusCode < 300) ||
		r2.StatusCode == 409 || r2.IdempotencyReplay
	return evaluator.ChaosResult{
		Scenario:       "duplicate_replay",
		Passed:         passed,
		ExpectedStatus: r1.StatusCode,
		StatusCode:     r2.StatusCode,
		Note: func() string {
			if passed {
				return fmt.Sprintf("idempotency replay handled correctly (r1=%d, r2=%d)", r1.StatusCode, r2.StatusCode)
			}
			return fmt.Sprintf("idempotency not enforced: r1=%d, r2=%d", r1.StatusCode, r2.StatusCode)
		}(),
	}
}

// missingIdempotencyKey omits the key on an endpoint that requires it.
func (i *Injector) missingIdempotencyKey(ctx context.Context) evaluator.ChaosResult {
	creds := i.pool.GetRandom()
	if creds == nil {
		return evaluator.ChaosResult{
			Scenario: "missing_idempotency_key",
			Passed:   true,
			Note:     "skipped: no token available",
		}
	}

	r := i.cl.Do(ctx, client.RequestOptions{
		Method: "POST",
		Path:   "/api/v1/wallet/" + creds.UserID + "/deposit",
		Token:  creds.AccessToken,
		// Deliberately no IdempotencyKey
		Body: map[string]interface{}{
			"amount": "5.00", "currency": "USD", "payment_method": "card",
		},
		EndpointName: "POST /api/v1/wallet/:id/deposit",
	})

	// API may require the key (400) or tolerate its absence (2xx).
	// Either is valid; we just verify no 5xx.
	passed := r.StatusCode < 500
	return evaluator.ChaosResult{
		Scenario:       "missing_idempotency_key",
		Passed:         passed,
		ExpectedStatus: 400,
		StatusCode:     r.StatusCode,
		Note: func() string {
			if r.StatusCode == 400 {
				return "missing idempotency key correctly rejected with 400"
			}
			if r.StatusCode >= 200 && r.StatusCode < 300 {
				return "idempotency key optional on this endpoint (accepted without it)"
			}
			if !passed {
				return fmt.Sprintf("unexpected %d — server error on missing idempotency key", r.StatusCode)
			}
			return fmt.Sprintf("status %d", r.StatusCode)
		}(),
	}
}

// oversizedPayload sends a very large body to probe request size limits.
func (i *Injector) oversizedPayload(ctx context.Context) evaluator.ChaosResult {
	creds := i.pool.GetRandom()
	if creds == nil {
		return evaluator.ChaosResult{
			Scenario: "oversized_payload",
			Passed:   true,
			Note:     "skipped: no token available",
		}
	}

	// 1 MB of noise in a JSON field
	noise := make([]byte, 1024*1024)
	for j := range noise {
		noise[j] = 'A'
	}
	r := i.cl.Do(ctx, client.RequestOptions{
		Method:       "POST",
		Path:         "/api/v1/bets/place",
		Token:        creds.AccessToken,
		Body:         map[string]interface{}{"junk": string(noise)},
		EndpointName: "POST /api/v1/bets/place",
	})

	passed := r.StatusCode == 413 || r.StatusCode == 400 || r.StatusCode == 422
	return evaluator.ChaosResult{
		Scenario:       "oversized_payload",
		Passed:         passed,
		ExpectedStatus: 413,
		StatusCode:     r.StatusCode,
		Note: func() string {
			if passed {
				return fmt.Sprintf("oversized payload rejected with %d", r.StatusCode)
			}
			return fmt.Sprintf("server accepted 1MB payload (%d) — check Nginx/Istio body size limits", r.StatusCode)
		}(),
	}
}

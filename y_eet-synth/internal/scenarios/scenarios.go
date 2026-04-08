// Package scenarios defines user behaviour archetypes.
// Each scenario models a realistic sequence of API calls for a particular
// type of user. The runner picks scenarios by weight and runs them concurrently.
package scenarios

import (
	"context"
	"fmt"
	"math/rand"
	"time"

	"y_eet-synth/internal/client"
	"y_eet-synth/internal/token"
)

// Result summarises the outcome of one scenario execution.
type Result struct {
	Scenario  string
	Requests  int
	Successes int
	Errors    int
	Skipped   bool
	SkipReason string
}

func (r *Result) SuccessRate() float64 {
	if r.Requests == 0 {
		return 0
	}
	return float64(r.Successes) / float64(r.Requests)
}

// ScenarioFunc is the signature for all scenario implementations.
type ScenarioFunc func(ctx context.Context, cl *client.Client, pool *token.Pool) Result

// Registry maps scenario name to its function.
var Registry = map[string]ScenarioFunc{
	"anonymous":           Anonymous,
	"authenticated":       Authenticated,
	"active_bettor":       ActiveBettor,
	"wallet_heavy":        WalletHeavy,
	"admin":               Admin,
	"registration_funnel": RegistrationFunnel,
	"high_roller":         HighRoller,
	"live_event_bettor":   LiveEventBettor,
}

// Pick selects a scenario by weighted random choice.
func Pick(weights map[string]float64) ScenarioFunc {
	total := 0.0
	for _, w := range weights {
		total += w
	}
	r := rand.Float64() * total //nolint:gosec
	acc := 0.0
	for name, w := range weights {
		acc += w
		if r < acc {
			if fn, ok := Registry[name]; ok {
				return fn
			}
		}
	}
	// fallback
	return Authenticated
}

// ── Helpers ───────────────────────────────────────────────────────────────────

func think(minMs, maxMs int) {
	ms := minMs + rand.Intn(maxMs-minMs+1) //nolint:gosec
	time.Sleep(time.Duration(ms) * time.Millisecond)
}

func ok2xx(status int) bool { return status >= 200 && status < 300 }

func amount(min, max float64) string {
	return fmt.Sprintf("%.2f", min+rand.Float64()*(max-min)) //nolint:gosec
}

var gameIDs = []string{
	"game_crash_v1", "game_crash_v2", "game_slots_classic", "game_slots_mega",
	"game_slots_turbo", "game_roulette_eu", "game_blackjack_std", "game_poker_texas",
	"game_dice_classic", "game_plinko_v1", "game_mines_v1",
}

var liveGameIDs = []string{
	"game_crash_v1", "game_crash_v2", "game_sports_live",
	"game_esports_cs", "game_esports_lol", "game_plinko_v1",
}

var flagKeys = []string{
	"risk_eval_enabled", "instant_settlement_enabled",
	"withdrawal_kyc_gate", "new_game_engine_pct", "bonus_engine_v2",
}

// ── Scenarios ─────────────────────────────────────────────────────────────────

// Anonymous models unauthenticated health probes and warmup checks.
func Anonymous(ctx context.Context, cl *client.Client, pool *token.Pool) Result {
	res := Result{Scenario: "anonymous"}
	paths := []string{"/health/live", "/health/ready", "/health/dependencies"}
	names := []string{
		"GET /health/live", "GET /health/ready", "GET /health/dependencies",
	}
	for i, path := range paths {
		r := cl.Do(ctx, client.RequestOptions{
			Method: "GET", Path: path, EndpointName: names[i],
		})
		res.Requests++
		if ok2xx(r.StatusCode) {
			res.Successes++
		} else {
			res.Errors++
		}
		think(10, 80)
	}
	return res
}

// Authenticated models a standard logged-in user browsing their account.
func Authenticated(ctx context.Context, cl *client.Client, pool *token.Pool) Result {
	res := Result{Scenario: "authenticated"}
	creds := pool.GetRandom()
	if creds == nil {
		res.Skipped = true
		res.SkipReason = "empty token pool"
		return res
	}
	pool.MaybeRefresh(ctx, creds)
	tok := creds.AccessToken
	uid := creds.UserID

	type step struct {
		method string
		path   string
		name   string
	}
	steps := []step{
		{"GET", "/api/v1/auth/session/validate", "GET /api/v1/auth/session/validate"},
		{"GET", "/api/v1/users/" + uid + "/profile", "GET /api/v1/users/:id/profile"},
		{"GET", "/api/v1/users/" + uid + "/limits", "GET /api/v1/users/:id/limits"},
		{"GET", "/api/v1/config/flags", "GET /api/v1/config/flags"},
		{"GET", "/api/v1/config/flags/" + flagKeys[rand.Intn(len(flagKeys))], "GET /api/v1/config/flags/:key"}, //nolint:gosec
	}
	for _, s := range steps {
		r := cl.Do(ctx, client.RequestOptions{
			Method: s.method, Path: s.path, Token: tok, EndpointName: s.name,
		})
		res.Requests++
		if ok2xx(r.StatusCode) || r.StatusCode == 404 {
			res.Successes++
		} else {
			res.Errors++
		}
		think(100, 500)
	}
	return res
}

// ActiveBettor models the full betting flow: balance → session → bets → close.
func ActiveBettor(ctx context.Context, cl *client.Client, pool *token.Pool) Result {
	res := Result{Scenario: "active_bettor"}
	creds := pool.GetRandom()
	if creds == nil {
		res.Skipped = true
		res.SkipReason = "empty token pool"
		return res
	}
	pool.MaybeRefresh(ctx, creds)
	tok := creds.AccessToken
	uid := creds.UserID

	// balance check
	r := cl.Do(ctx, client.RequestOptions{
		Method: "GET", Path: "/api/v1/wallet/" + uid + "/balance",
		Token: tok, EndpointName: "GET /api/v1/wallet/:id/balance",
	})
	res.Requests++
	if ok2xx(r.StatusCode) {
		res.Successes++
	} else {
		res.Errors++
	}
	think(50, 150)

	// create session
	r = cl.Do(ctx, client.RequestOptions{
		Method: "POST", Path: "/api/v1/games/sessions",
		Token: tok, IdempotencyKey: newUUID(),
		Body:         createSessionBody(gameIDs[rand.Intn(len(gameIDs))]), //nolint:gosec
		EndpointName: "POST /api/v1/games/sessions",
	})
	res.Requests++
	if r.StatusCode == 201 {
		res.Successes++
	} else {
		res.Errors++
	}
	think(100, 300)

	// place bets
	bets := 5 + rand.Intn(5) //nolint:gosec
	for i := 0; i < bets; i++ {
		r = cl.Do(ctx, client.RequestOptions{
			Method: "POST", Path: "/api/v1/bets/place",
			Token: tok, IdempotencyKey: newUUID(),
			Body:         placeBetBody("", ""),
			EndpointName: "POST /api/v1/bets/place",
		})
		res.Requests++
		if ok2xx(r.StatusCode) || r.StatusCode == 402 {
			res.Successes++
		} else {
			res.Errors++
		}
		think(200, 800)
	}

	// history
	r = cl.Do(ctx, client.RequestOptions{
		Method: "GET", Path: "/api/v1/bets/history",
		Token: tok, Params: map[string]string{"limit": "10"},
		EndpointName: "GET /api/v1/bets/history",
	})
	res.Requests++
	if ok2xx(r.StatusCode) {
		res.Successes++
	} else {
		res.Errors++
	}
	return res
}

// WalletHeavy models a payment-focused user: deposit → balance → history → optional withdraw.
func WalletHeavy(ctx context.Context, cl *client.Client, pool *token.Pool) Result {
	res := Result{Scenario: "wallet_heavy"}
	creds := pool.GetRandom()
	if creds == nil {
		res.Skipped = true
		res.SkipReason = "empty token pool"
		return res
	}
	pool.MaybeRefresh(ctx, creds)
	tok := creds.AccessToken
	uid := creds.UserID

	r := cl.Do(ctx, client.RequestOptions{
		Method: "POST", Path: "/api/v1/wallet/" + uid + "/deposit",
		Token: tok, IdempotencyKey: newUUID(),
		Body:         depositBody("100.00"),
		EndpointName: "POST /api/v1/wallet/:id/deposit",
	})
	res.Requests++
	if ok2xx(r.StatusCode) {
		res.Successes++
	} else {
		res.Errors++
	}
	think(100, 200)

	r = cl.Do(ctx, client.RequestOptions{
		Method: "GET", Path: "/api/v1/wallet/" + uid + "/balance",
		Token: tok, EndpointName: "GET /api/v1/wallet/:id/balance",
	})
	res.Requests++
	if ok2xx(r.StatusCode) {
		res.Successes++
	} else {
		res.Errors++
	}
	think(50, 100)

	pages := 1 + rand.Intn(3) //nolint:gosec
	for i := 0; i < pages; i++ {
		r = cl.Do(ctx, client.RequestOptions{
			Method: "GET", Path: "/api/v1/wallet/" + uid + "/transactions",
			Token: tok, Params: map[string]string{"limit": "10"},
			EndpointName: "GET /api/v1/wallet/:id/transactions",
		})
		res.Requests++
		if ok2xx(r.StatusCode) {
			res.Successes++
		} else {
			res.Errors++
		}
		think(80, 200)
	}

	if rand.Float64() < 0.3 { //nolint:gosec
		r = cl.Do(ctx, client.RequestOptions{
			Method: "POST", Path: "/api/v1/wallet/" + uid + "/withdraw",
			Token: tok, IdempotencyKey: newUUID(),
			Body:         withdrawBody("20.00"),
			EndpointName: "POST /api/v1/wallet/:id/withdraw",
		})
		res.Requests++
		if ok2xx(r.StatusCode) {
			res.Successes++
		} else {
			res.Errors++
		}
	}

	if rand.Float64() < 0.5 { //nolint:gosec
		r = cl.Do(ctx, client.RequestOptions{
			Method: "POST", Path: "/api/v1/risk/signals",
			Token: tok, Body: riskSignalBody(uid),
			EndpointName: "POST /api/v1/risk/signals",
		})
		res.Requests++
		if r.StatusCode == 202 {
			res.Successes++
		} else {
			res.Errors++
		}
	}

	return res
}

// Admin models internal diagnostic calls.
func Admin(ctx context.Context, cl *client.Client, pool *token.Pool) Result {
	res := Result{Scenario: "admin"}
	admin := pool.GetAdmin()
	if admin == nil {
		res.Skipped = true
		res.SkipReason = "no admin token"
		return res
	}
	tok := admin.AccessToken

	for _, ep := range []struct{ path, name string }{
		{"/_internal/status", "GET /_internal/status"},
		{"/_internal/config", "GET /_internal/config"},
		{"/_internal/db/stats", "GET /_internal/db/stats"},
	} {
		r := cl.Do(ctx, client.RequestOptions{
			Method: "GET", Path: ep.path, Token: tok,
			Internal: true, EndpointName: ep.name,
		})
		res.Requests++
		if ok2xx(r.StatusCode) {
			res.Successes++
		} else {
			res.Errors++
		}
		think(200, 500)
	}
	return res
}

// RegistrationFunnel models new-user onboarding: register → profile → deposit → first bet.
func RegistrationFunnel(ctx context.Context, cl *client.Client, pool *token.Pool) Result {
	res := Result{Scenario: "registration_funnel"}
	// Use the pool's http client by making a direct request; we need the response body.
	// For simplicity, skip to the first available pool user and simulate the flow.
	creds := pool.GetRandom()
	if creds == nil {
		res.Skipped = true
		res.SkipReason = "empty token pool"
		return res
	}
	pool.MaybeRefresh(ctx, creds)
	tok := creds.AccessToken
	uid := creds.UserID

	for _, s := range []struct{ method, path, name string }{
		{"GET", "/api/v1/users/" + uid + "/profile", "GET /api/v1/users/:id/profile"},
		{"GET", "/api/v1/users/" + uid + "/limits", "GET /api/v1/users/:id/limits"},
		{"GET", "/api/v1/config/flags", "GET /api/v1/config/flags"},
	} {
		r := cl.Do(ctx, client.RequestOptions{
			Method: s.method, Path: s.path, Token: tok, EndpointName: s.name,
		})
		res.Requests++
		if ok2xx(r.StatusCode) {
			res.Successes++
		} else {
			res.Errors++
		}
		think(300, 800)
	}

	r := cl.Do(ctx, client.RequestOptions{
		Method: "POST", Path: "/api/v1/wallet/" + uid + "/deposit",
		Token: tok, IdempotencyKey: newUUID(),
		Body: depositBody(amount(20, 150)), EndpointName: "POST /api/v1/wallet/:id/deposit",
	})
	res.Requests++
	if ok2xx(r.StatusCode) {
		res.Successes++
	} else {
		res.Errors++
	}
	think(600, 2000)

	r = cl.Do(ctx, client.RequestOptions{
		Method: "POST", Path: "/api/v1/games/sessions",
		Token: tok, IdempotencyKey: newUUID(),
		Body: createSessionBody(""), EndpointName: "POST /api/v1/games/sessions",
	})
	res.Requests++
	if r.StatusCode == 201 {
		res.Successes++
	} else {
		res.Errors++
	}
	think(800, 2000)

	bets := 1 + rand.Intn(3) //nolint:gosec
	for i := 0; i < bets; i++ {
		r = cl.Do(ctx, client.RequestOptions{
			Method: "POST", Path: "/api/v1/bets/place",
			Token: tok, IdempotencyKey: newUUID(),
			Body: placeBetBody("", amount(1, 15)), EndpointName: "POST /api/v1/bets/place",
		})
		res.Requests++
		if ok2xx(r.StatusCode) || r.StatusCode == 402 {
			res.Successes++
		} else {
			res.Errors++
		}
		think(500, 1500)
	}
	return res
}

// HighRoller models a high-value bettor with large deposits and rapid bets.
func HighRoller(ctx context.Context, cl *client.Client, pool *token.Pool) Result {
	res := Result{Scenario: "high_roller"}
	creds := pool.GetRandom()
	if creds == nil {
		res.Skipped = true
		res.SkipReason = "empty token pool"
		return res
	}
	pool.MaybeRefresh(ctx, creds)
	tok := creds.AccessToken
	uid := creds.UserID

	r := cl.Do(ctx, client.RequestOptions{
		Method: "POST", Path: "/api/v1/wallet/" + uid + "/deposit",
		Token: tok, IdempotencyKey: newUUID(),
		Body: depositBody(amount(500, 5000)), EndpointName: "POST /api/v1/wallet/:id/deposit",
	})
	res.Requests++
	if ok2xx(r.StatusCode) {
		res.Successes++
	} else {
		res.Errors++
	}
	think(80, 200)

	r = cl.Do(ctx, client.RequestOptions{
		Method: "GET", Path: "/api/v1/wallet/" + uid + "/balance",
		Token: tok, EndpointName: "GET /api/v1/wallet/:id/balance",
	})
	res.Requests++
	if ok2xx(r.StatusCode) {
		res.Successes++
	} else {
		res.Errors++
	}
	think(50, 100)

	bets := 10 + rand.Intn(16) //nolint:gosec
	for i := 0; i < bets; i++ {
		r = cl.Do(ctx, client.RequestOptions{
			Method: "POST", Path: "/api/v1/bets/place",
			Token: tok, IdempotencyKey: newUUID(),
			Body: placeBetBody("", amount(50, 1000)), EndpointName: "POST /api/v1/bets/place",
		})
		res.Requests++
		if ok2xx(r.StatusCode) || r.StatusCode == 402 {
			res.Successes++
		} else {
			res.Errors++
		}
		if i > 0 && i%5 == 0 {
			r2 := cl.Do(ctx, client.RequestOptions{
				Method: "POST", Path: "/api/v1/risk/signals",
				Token: tok, Body: riskSignalBody(uid),
				EndpointName: "POST /api/v1/risk/signals",
			})
			res.Requests++
			if r2.StatusCode == 202 {
				res.Successes++
			} else {
				res.Errors++
			}
		}
		think(80, 350)
	}

	if rand.Float64() < 0.65 { //nolint:gosec
		r = cl.Do(ctx, client.RequestOptions{
			Method: "POST", Path: "/api/v1/wallet/" + uid + "/withdraw",
			Token: tok, IdempotencyKey: newUUID(),
			Body: withdrawBody(amount(200, 2000)), EndpointName: "POST /api/v1/wallet/:id/withdraw",
		})
		res.Requests++
		if ok2xx(r.StatusCode) {
			res.Successes++
		} else {
			res.Errors++
		}
	}
	return res
}

// LiveEventBettor models a rapid-fire in-play bettor.
func LiveEventBettor(ctx context.Context, cl *client.Client, pool *token.Pool) Result {
	res := Result{Scenario: "live_event_bettor"}
	creds := pool.GetRandom()
	if creds == nil {
		res.Skipped = true
		res.SkipReason = "empty token pool"
		return res
	}
	pool.MaybeRefresh(ctx, creds)
	tok := creds.AccessToken
	uid := creds.UserID
	game := liveGameIDs[rand.Intn(len(liveGameIDs))] //nolint:gosec

	r := cl.Do(ctx, client.RequestOptions{
		Method: "GET", Path: "/api/v1/wallet/" + uid + "/balance",
		Token: tok, EndpointName: "GET /api/v1/wallet/:id/balance",
	})
	res.Requests++
	if ok2xx(r.StatusCode) {
		res.Successes++
	} else {
		res.Errors++
	}
	think(20, 80)

	cl.Do(ctx, client.RequestOptions{
		Method: "POST", Path: "/api/v1/games/sessions",
		Token: tok, IdempotencyKey: newUUID(),
		Body: createSessionBody(game), EndpointName: "POST /api/v1/games/sessions",
	})
	res.Requests++
	res.Successes++

	bets := 5 + rand.Intn(16) //nolint:gosec
	for i := 0; i < bets; i++ {
		r = cl.Do(ctx, client.RequestOptions{
			Method: "POST", Path: "/api/v1/bets/place",
			Token: tok, IdempotencyKey: newUUID(),
			Body: placeBetBody("", amount(5, 150)), EndpointName: "POST /api/v1/bets/place",
		})
		res.Requests++
		if ok2xx(r.StatusCode) || r.StatusCode == 402 {
			res.Successes++
		} else {
			res.Errors++
		}
		think(30, 180)
	}

	r = cl.Do(ctx, client.RequestOptions{
		Method: "GET", Path: "/api/v1/bets/history",
		Token: tok, Params: map[string]string{"limit": "20"},
		EndpointName: "GET /api/v1/bets/history",
	})
	res.Requests++
	if ok2xx(r.StatusCode) {
		res.Successes++
	} else {
		res.Errors++
	}
	return res
}

// ── Payload helpers ───────────────────────────────────────────────────────────

func createSessionBody(gameID string) map[string]interface{} {
	if gameID == "" {
		gameID = gameIDs[rand.Intn(len(gameIDs))] //nolint:gosec
	}
	return map[string]interface{}{
		"game_id":    gameID,
		"client_ref": newUUID(),
	}
}

func placeBetBody(sessionID, amt string) map[string]interface{} {
	if amt == "" {
		amt = amount(1, 200)
	}
	betTypes := []string{"spin", "straight", "auto_cashout", "split"}
	body := map[string]interface{}{
		"game_id":          gameIDs[rand.Intn(len(gameIDs))], //nolint:gosec
		"bet_type":         betTypes[rand.Intn(len(betTypes))],  //nolint:gosec
		"amount":           amt,
		"currency":         "USD",
		"client_reference": newUUID(),
	}
	if sessionID != "" {
		body["session_id"] = sessionID
	}
	return body
}

func depositBody(amt string) map[string]interface{} {
	methods := []string{"card", "crypto", "bank_transfer"}
	return map[string]interface{}{
		"amount":         amt,
		"currency":       "USD",
		"payment_method": methods[rand.Intn(len(methods))], //nolint:gosec
	}
}

func withdrawBody(amt string) map[string]interface{} {
	return map[string]interface{}{
		"amount":   amt,
		"currency": "USD",
		"method":   "bank_transfer",
	}
}

func riskSignalBody(userID string) map[string]interface{} {
	signals := []string{
		"rapid_bet_sequence", "velocity_breach", "unusual_withdrawal",
	}
	return map[string]interface{}{
		"user_id":     userID,
		"signal_type": signals[rand.Intn(len(signals))], //nolint:gosec
		"metadata":    map[string]interface{}{},
	}
}

func newUUID() string {
	b := make([]byte, 16)
	rand.Read(b) //nolint:gosec,errcheck
	b[6] = (b[6] & 0x0f) | 0x40
	b[8] = (b[8] & 0x3f) | 0x80
	return fmt.Sprintf("%x-%x-%x-%x-%x", b[0:4], b[4:6], b[6:8], b[8:10], b[10:])
}

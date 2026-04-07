// Package token manages a pool of synthetic user JWT credentials.
package token

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"math/rand"
	"net/http"
	"strings"
	"sync"
	"time"
)

const refreshThreshold = 12 * time.Minute

// Credentials holds login state for a single synthetic user.
type Credentials struct {
	UserID       string
	Email        string
	Password     string
	Username     string
	AccessToken  string
	RefreshToken string
	IssuedAt     time.Time
	Roles        []string
}

func (c *Credentials) NeedsRefresh() bool {
	return time.Since(c.IssuedAt) > refreshThreshold
}

func (c *Credentials) IsAdmin() bool {
	for _, r := range c.Roles {
		if r == "admin" {
			return true
		}
	}
	return false
}

// Pool holds pre-seeded user credentials for scenario use.
type Pool struct {
	mu       sync.RWMutex
	users    []*Credentials
	admin    *Credentials
	baseURL  string
	httpCl   *http.Client
	poolSize int
	seedAdmin bool
}

// New creates a Pool.
func New(baseURL string, poolSize int, seedAdmin bool) *Pool {
	return &Pool{
		baseURL:   strings.TrimRight(baseURL, "/"),
		poolSize:  poolSize,
		seedAdmin: seedAdmin,
		httpCl: &http.Client{
			Timeout: 30 * time.Second,
		},
	}
}

// Seed registers poolSize users and optionally logs in the admin.
func (p *Pool) Seed(ctx context.Context) {
	log.Printf("Token pool: seeding %d synthetic users...", p.poolSize)

	sem := make(chan struct{}, 10) // bounded concurrency
	var wg sync.WaitGroup
	var mu sync.Mutex
	var users []*Credentials

	for i := 0; i < p.poolSize; i++ {
		wg.Add(1)
		sem <- struct{}{}
		go func() {
			defer wg.Done()
			defer func() { <-sem }()
			creds, err := p.register(ctx)
			if err != nil {
				log.Printf("Token pool: register failed: %v", err)
				return
			}
			mu.Lock()
			users = append(users, creds)
			mu.Unlock()
		}()
	}
	wg.Wait()

	p.mu.Lock()
	p.users = users
	p.mu.Unlock()

	if p.seedAdmin {
		admin, err := p.loginExisting(ctx, "admin@y_eet.com", "Admin1234!")
		if err != nil {
			log.Printf("Token pool: admin login failed: %v", err)
		} else {
			admin.Roles = []string{"admin", "player"}
			p.mu.Lock()
			p.admin = admin
			p.mu.Unlock()
			log.Printf("Token pool: admin token acquired")
		}
	}

	p.mu.RLock()
	n := len(p.users)
	hasAdmin := p.admin != nil
	p.mu.RUnlock()
	log.Printf("Token pool: ready — %d regular users, admin=%v", n, hasAdmin)
}

// GetRandom returns a random user credential (nil if pool is empty).
func (p *Pool) GetRandom() *Credentials {
	p.mu.RLock()
	defer p.mu.RUnlock()
	if len(p.users) == 0 {
		return nil
	}
	return p.users[rand.Intn(len(p.users))] //nolint:gosec
}

// GetAdmin returns the admin credential (nil if not seeded).
func (p *Pool) GetAdmin() *Credentials {
	p.mu.RLock()
	defer p.mu.RUnlock()
	return p.admin
}

// MaybeRefresh refreshes a credential's token if it is approaching expiry.
func (p *Pool) MaybeRefresh(ctx context.Context, creds *Credentials) {
	if !creds.NeedsRefresh() {
		return
	}
	body, _ := json.Marshal(map[string]string{"refresh_token": creds.RefreshToken})
	req, err := http.NewRequestWithContext(ctx, "POST",
		p.baseURL+"/api/v1/auth/refresh", bytes.NewReader(body))
	if err != nil {
		return
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Synthetic", "true")

	resp, err := p.httpCl.Do(req)
	if err != nil || resp.StatusCode != 200 {
		if resp != nil {
			resp.Body.Close()
		}
		return
	}
	defer resp.Body.Close()

	var data struct {
		AccessToken string `json:"access_token"`
	}
	if json.NewDecoder(resp.Body).Decode(&data) == nil && data.AccessToken != "" {
		p.mu.Lock()
		creds.AccessToken = data.AccessToken
		creds.IssuedAt = time.Now()
		p.mu.Unlock()
	}
}

// ── Private helpers ───────────────────────────────────────────────────────────

func (p *Pool) register(ctx context.Context) (*Credentials, error) {
	payload := registerPayload()
	body, _ := json.Marshal(payload)
	req, err := http.NewRequestWithContext(ctx, "POST",
		p.baseURL+"/api/v1/auth/register", bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Synthetic", "true")

	resp, err := p.httpCl.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != 201 {
		b, _ := io.ReadAll(resp.Body)
		return nil, fmt.Errorf("register returned %d: %s", resp.StatusCode, string(b)[:min(120, len(b))])
	}

	var data struct {
		UserID       string `json:"user_id"`
		Username     string `json:"username"`
		AccessToken  string `json:"access_token"`
		RefreshToken string `json:"refresh_token"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&data); err != nil {
		return nil, err
	}

	return &Credentials{
		UserID:       data.UserID,
		Email:        payload["email"].(string),
		Password:     payload["password"].(string),
		Username:     data.Username,
		AccessToken:  data.AccessToken,
		RefreshToken: data.RefreshToken,
		IssuedAt:     time.Now(),
		Roles:        []string{"player"},
	}, nil
}

func (p *Pool) loginExisting(ctx context.Context, email, password string) (*Credentials, error) {
	body, _ := json.Marshal(map[string]interface{}{
		"email":    email,
		"password": password,
	})
	req, err := http.NewRequestWithContext(ctx, "POST",
		p.baseURL+"/api/v1/auth/token", bytes.NewReader(body))
	if err != nil {
		return nil, err
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Synthetic", "true")

	resp, err := p.httpCl.Do(req)
	if err != nil {
		return nil, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("login returned %d", resp.StatusCode)
	}

	var data struct {
		SessionID    string `json:"session_id"`
		AccessToken  string `json:"access_token"`
		RefreshToken string `json:"refresh_token"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&data); err != nil {
		return nil, err
	}

	return &Credentials{
		UserID:       data.SessionID,
		Email:        email,
		Password:     password,
		Username:     strings.Split(email, "@")[0],
		AccessToken:  data.AccessToken,
		RefreshToken: data.RefreshToken,
		IssuedAt:     time.Now(),
	}, nil
}

// ── Payload factory ───────────────────────────────────────────────────────────

var adjectives = []string{
	"swift", "bright", "calm", "daring", "eager",
	"fierce", "gentle", "happy", "idle", "jolly",
}
var nouns = []string{
	"badger", "crane", "dingo", "eagle", "falcon",
	"gopher", "heron", "ibis", "jaguar", "kestrel",
}
var domains = []string{"gmail.com", "yahoo.com", "protonmail.com", "outlook.com"}

func registerPayload() map[string]interface{} {
	adj := adjectives[rand.Intn(len(adjectives))]   //nolint:gosec
	noun := nouns[rand.Intn(len(nouns))]             //nolint:gosec
	domain := domains[rand.Intn(len(domains))]       //nolint:gosec
	n := rand.Intn(9999)                              //nolint:gosec
	username := fmt.Sprintf("%s_%s_%04d", adj, noun, n)
	email := fmt.Sprintf("%s@%s", username, domain)
	password := fmt.Sprintf("Pass!%04d%s", n, strings.ToUpper(adj[:2]))
	return map[string]interface{}{
		"username":           username,
		"email":              email,
		"password":           password,
		"date_of_birth":      "1990-06-15",
		"jurisdiction":       "GB",
		"currency":           "USD",
		"device_fingerprint": randomHex16(),
	}
}

func randomHex16() string {
	b := make([]byte, 16)
	rand.Read(b) //nolint:gosec,errcheck
	return fmt.Sprintf("%x", b)
}

func min(a, b int) int {
	if a < b {
		return a
	}
	return b
}

// Package client provides the synthetic HTTP client used by all scenarios.
// Every request receives X-Synthetic, X-Request-ID, traceparent, and optional
// Authorization / Idempotency-Key headers. Istio / Envoy response headers are
// captured and surfaced through RequestRecord.
package client

import (
	"context"
	"crypto/rand"
	"crypto/tls"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"time"

	"y_eet-synth/internal/metrics"
)

// Client is the synthetic HTTP client. Create one per run and share it.
type Client struct {
	BaseURL         string
	InternalBaseURL string
	Metrics         *metrics.Collector
	XSynthetic      bool

	http *http.Client
}

// Options configures the client.
type Options struct {
	BaseURL               string
	InternalBaseURL       string
	Metrics               *metrics.Collector
	RequestTimeoutSeconds float64
	TLSVerify             bool
	XSynthetic            bool
	MaxIdleConns          int
}

// New creates a Client.
func New(opts Options) *Client {
	transport := &http.Transport{
		MaxIdleConns:        opts.MaxIdleConns,
		MaxIdleConnsPerHost: opts.MaxIdleConns,
		IdleConnTimeout:     90 * time.Second,
	}
	if !opts.TLSVerify {
		transport.TLSClientConfig = &tls.Config{InsecureSkipVerify: true} //nolint:gosec
	}

	timeout := 30.0
	if opts.RequestTimeoutSeconds > 0 {
		timeout = opts.RequestTimeoutSeconds
	}
	if opts.MaxIdleConns == 0 {
		transport.MaxIdleConns = 200
		transport.MaxIdleConnsPerHost = 200
	}

	return &Client{
		BaseURL:         strings.TrimRight(opts.BaseURL, "/"),
		InternalBaseURL: strings.TrimRight(opts.InternalBaseURL, "/"),
		Metrics:         opts.Metrics,
		XSynthetic:      opts.XSynthetic,
		http: &http.Client{
			Timeout:   time.Duration(timeout * float64(time.Second)),
			Transport: transport,
		},
	}
}

// RequestOptions controls a single request.
type RequestOptions struct {
	Method         string
	Path           string
	Internal       bool
	Token          string
	IdempotencyKey string
	Body           interface{} // marshalled to JSON
	Params         map[string]string
	EndpointName   string // display name for metrics; defaults to "METHOD /path"
}

// Do executes a request and returns a RequestRecord.
func (c *Client) Do(ctx context.Context, opts RequestOptions) metrics.RequestRecord {
	base := c.BaseURL
	if opts.Internal {
		base = c.InternalBaseURL
	}

	ep := opts.EndpointName
	if ep == "" {
		ep = fmt.Sprintf("%s %s", opts.Method, opts.Path)
	}

	url := base + opts.Path
	if len(opts.Params) > 0 {
		parts := make([]string, 0, len(opts.Params))
		for k, v := range opts.Params {
			parts = append(parts, k+"="+v)
		}
		url += "?" + strings.Join(parts, "&")
	}

	// Build body
	var bodyReader io.Reader
	if opts.Body != nil {
		b, _ := json.Marshal(opts.Body)
		bodyReader = strings.NewReader(string(b))
	}

	req, err := http.NewRequestWithContext(ctx, opts.Method, url, bodyReader)
	if err != nil {
		rec := metrics.RequestRecord{
			Endpoint:  ep,
			Method:    opts.Method,
			Timeout:   true,
			LatencyMs: 0,
		}
		c.Metrics.Record(rec)
		return rec
	}

	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Request-ID", newUUID())
	if c.XSynthetic {
		req.Header.Set("X-Synthetic", "true")
	}
	if opts.Token != "" {
		req.Header.Set("Authorization", "Bearer "+opts.Token)
	}
	if opts.IdempotencyKey != "" {
		req.Header.Set("Idempotency-Key", opts.IdempotencyKey)
	}

	// W3C traceparent
	traceID := randomHex(16)
	spanID := randomHex(8)
	traceparent := fmt.Sprintf("00-%s-%s-01", traceID, spanID)
	req.Header.Set("traceparent", traceparent)

	start := time.Now()
	resp, err := c.http.Do(req)
	latencyMs := float64(time.Since(start).Milliseconds())

	rec := metrics.RequestRecord{
		Endpoint:        ep,
		Method:          opts.Method,
		LatencyMs:       latencyMs,
		TraceparentSent: true,
		EnvoyAttemptCount: 1,
	}

	if err != nil {
		if ctx.Err() != nil || isTimeout(err) {
			rec.Timeout = true
		}
		c.Metrics.Record(rec)
		return rec
	}
	defer resp.Body.Close()
	io.Copy(io.Discard, resp.Body) //nolint:errcheck

	rec.StatusCode = resp.StatusCode
	rec.AuthFailed = resp.StatusCode == 401 || resp.StatusCode == 403

	// Capture Istio / Envoy headers
	if ac := resp.Header.Get("X-Envoy-Attempt-Count"); ac != "" {
		n := 0
		fmt.Sscanf(ac, "%d", &n)
		if n > 0 {
			rec.EnvoyAttemptCount = n
		}
	}
	if up := resp.Header.Get("X-Envoy-Upstream-Service-Time"); up != "" {
		fmt.Sscanf(up, "%f", &rec.EnvoyUpstreamMs)
	}
	server := resp.Header.Get("Server")
	rec.ViaIstio = strings.Contains(server, "istio-envoy") || strings.Contains(server, "envoy")
	rec.TraceparentReceived = resp.Header.Get("Traceparent") != ""
	rec.CanaryVersion = firstNonEmpty(
		resp.Header.Get("X-Canary-Version"),
		resp.Header.Get("X-Version"),
		resp.Header.Get("X-App-Version"),
	)
	rec.IdempotencyReplay = strings.EqualFold(resp.Header.Get("X-Idempotency-Replay"), "true")

	if rec.EnvoyAttemptCount > 1 {
		rec.RetryCount = rec.EnvoyAttemptCount - 1
	}

	c.Metrics.Record(rec)
	return rec
}

// DoJSON executes a request and decodes the response body into dest (may be nil).
func (c *Client) DoJSON(ctx context.Context, opts RequestOptions, dest interface{}) (metrics.RequestRecord, error) {
	base := c.BaseURL
	if opts.Internal {
		base = c.InternalBaseURL
	}

	ep := opts.EndpointName
	if ep == "" {
		ep = fmt.Sprintf("%s %s", opts.Method, opts.Path)
	}

	url := base + opts.Path

	var bodyReader io.Reader
	if opts.Body != nil {
		b, _ := json.Marshal(opts.Body)
		bodyReader = strings.NewReader(string(b))
	}

	req, err := http.NewRequestWithContext(ctx, opts.Method, url, bodyReader)
	if err != nil {
		return metrics.RequestRecord{Endpoint: ep, Method: opts.Method}, err
	}

	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("X-Request-ID", newUUID())
	if c.XSynthetic {
		req.Header.Set("X-Synthetic", "true")
	}
	if opts.Token != "" {
		req.Header.Set("Authorization", "Bearer "+opts.Token)
	}

	traceID := randomHex(16)
	spanID := randomHex(8)
	req.Header.Set("traceparent", fmt.Sprintf("00-%s-%s-01", traceID, spanID))

	start := time.Now()
	resp, err := c.http.Do(req)
	latencyMs := float64(time.Since(start).Milliseconds())

	if err != nil {
		rec := metrics.RequestRecord{
			Endpoint:  ep,
			Method:    opts.Method,
			LatencyMs: latencyMs,
			Timeout:   isTimeout(err),
		}
		c.Metrics.Record(rec)
		return rec, err
	}
	defer resp.Body.Close()

	rec := metrics.RequestRecord{
		Endpoint:          ep,
		Method:            opts.Method,
		StatusCode:        resp.StatusCode,
		LatencyMs:         latencyMs,
		TraceparentSent:   true,
		EnvoyAttemptCount: 1,
		AuthFailed:        resp.StatusCode == 401 || resp.StatusCode == 403,
	}

	if dest != nil && resp.StatusCode < 300 {
		if decErr := json.NewDecoder(resp.Body).Decode(dest); decErr != nil {
			io.Copy(io.Discard, resp.Body) //nolint:errcheck
		}
	} else {
		io.Copy(io.Discard, resp.Body) //nolint:errcheck
	}

	c.Metrics.Record(rec)
	return rec, nil
}

// ── Helpers ───────────────────────────────────────────────────────────────────

func newUUID() string {
	var b [16]byte
	rand.Read(b[:]) //nolint:errcheck
	b[6] = (b[6] & 0x0f) | 0x40
	b[8] = (b[8] & 0x3f) | 0x80
	return fmt.Sprintf("%x-%x-%x-%x-%x", b[0:4], b[4:6], b[6:8], b[8:10], b[10:])
}

func randomHex(n int) string {
	b := make([]byte, n)
	rand.Read(b) //nolint:errcheck
	return hex.EncodeToString(b)
}

func firstNonEmpty(ss ...string) string {
	for _, s := range ss {
		if s != "" {
			return s
		}
	}
	return ""
}

func isTimeout(err error) bool {
	if err == nil {
		return false
	}
	s := err.Error()
	return strings.Contains(s, "timeout") ||
		strings.Contains(s, "deadline") ||
		strings.Contains(s, "context deadline exceeded")
}

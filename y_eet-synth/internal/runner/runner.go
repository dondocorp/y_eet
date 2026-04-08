// Package runner drives concurrent traffic generation.
// It implements a token-bucket rate limiter, configurable concurrency,
// burst windows, and graceful shutdown.
package runner

import (
	"context"
	"log"
	"os"
	"os/signal"
	"sync"
	"sync/atomic"
	"syscall"
	"time"

	"y_eet-synth/internal/client"
	"y_eet-synth/internal/config"
	"y_eet-synth/internal/metrics"
	"y_eet-synth/internal/scenarios"
	"y_eet-synth/internal/token"
)

// tokenBucket is a simple token-bucket rate limiter.
type tokenBucket struct {
	mu       sync.Mutex
	tokens   float64
	capacity float64
	rate     float64
	lastFill time.Time
}

func newTokenBucket(rps float64) *tokenBucket {
	cap := rps
	if cap < 1 {
		cap = 1
	}
	return &tokenBucket{
		tokens:   cap,
		capacity: cap,
		rate:     rps,
		lastFill: time.Now(),
	}
}

func (tb *tokenBucket) setRate(rps float64) {
	tb.mu.Lock()
	defer tb.mu.Unlock()
	tb.rate = rps
	if rps > tb.capacity {
		tb.capacity = rps
	}
}

func (tb *tokenBucket) acquire(ctx context.Context) bool {
	if tb.rate <= 0 {
		return true // unlimited
	}
	for {
		tb.mu.Lock()
		now := time.Now()
		elapsed := now.Sub(tb.lastFill).Seconds()
		tb.tokens += elapsed * tb.rate
		if tb.tokens > tb.capacity {
			tb.tokens = tb.capacity
		}
		tb.lastFill = now
		if tb.tokens >= 1.0 {
			tb.tokens -= 1.0
			tb.mu.Unlock()
			return true
		}
		tb.mu.Unlock()

		select {
		case <-ctx.Done():
			return false
		case <-time.After(5 * time.Millisecond):
		}
	}
}

// Runner executes traffic concurrently according to a ProfileConfig.
type Runner struct {
	client  *client.Client
	pool    *token.Pool
	metrics *metrics.Collector
	profile config.ProfileConfig

	scenarioCount int64
}

// New creates a Runner.
func New(
	cl *client.Client,
	pool *token.Pool,
	m *metrics.Collector,
	profile config.ProfileConfig,
) *Runner {
	return &Runner{
		client:  cl,
		pool:    pool,
		metrics: m,
		profile: profile,
	}
}

// Run starts traffic until the profile duration expires or a signal is received.
func (r *Runner) Run(ctx context.Context) {
	profile := r.profile
	ctx, cancel := context.WithTimeout(ctx, time.Duration(profile.DurationSeconds)*time.Second)
	defer cancel()

	// Listen for SIGINT / SIGTERM
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
	go func() {
		select {
		case <-sigCh:
			log.Println("[runner] signal received — stopping")
			cancel()
		case <-ctx.Done():
		}
	}()

	bucket := newTokenBucket(profile.RPSTarget)

	// Burst window manager
	if profile.BurstFactor > 1.0 {
		go func() {
			for {
				select {
				case <-ctx.Done():
					return
				case <-time.After(time.Duration(profile.BurstIntervalSeconds) * time.Second):
					log.Printf("[runner] burst window open (%.1fx for %ds)",
						profile.BurstFactor, profile.BurstDurationSeconds)
					bucket.setRate(profile.RPSTarget * profile.BurstFactor)
					select {
					case <-ctx.Done():
						return
					case <-time.After(time.Duration(profile.BurstDurationSeconds) * time.Second):
					}
					bucket.setRate(profile.RPSTarget)
					log.Println("[runner] burst window closed")
				}
			}
		}()
	}

	// Progress logger
	go func() {
		for {
			select {
			case <-ctx.Done():
				return
			case <-time.After(10 * time.Second):
				snap := r.metrics.Snapshot()
				total := 0
				errors := 0
				for _, m := range snap {
					total += m.Total
					errors += m.ServerError + m.Timeout
				}
				errPct := 0.0
				if total > 0 {
					errPct = float64(errors) / float64(total) * 100
				}
				log.Printf("[runner] elapsed=%.0fs scenarios=%d requests=%d rps=%.1f error_rate=%.2f%% p99=%.0fms",
					r.metrics.ElapsedSeconds(),
					atomic.LoadInt64(&r.scenarioCount),
					total,
					r.metrics.RPS(),
					errPct,
					r.metrics.GlobalP99(),
				)
			}
		}
	}()

	sem := make(chan struct{}, profile.Concurrency)
	var wg sync.WaitGroup

	for {
		select {
		case <-ctx.Done():
			goto done
		default:
		}

		if !bucket.acquire(ctx) {
			goto done
		}

		// Try to acquire semaphore slot
		select {
		case <-ctx.Done():
			goto done
		case sem <- struct{}{}:
		}

		wg.Add(1)
		go func() {
			defer wg.Done()
			defer func() { <-sem }()

			fn := scenarios.Pick(profile.ScenarioWeights)
			fn(ctx, r.client, r.pool) //nolint:errcheck
			atomic.AddInt64(&r.scenarioCount, 1)
		}()
	}

done:
	wg.Wait()
	log.Printf("[runner] complete: %d scenarios, %.1f rps average",
		atomic.LoadInt64(&r.scenarioCount), r.metrics.RPS())
}

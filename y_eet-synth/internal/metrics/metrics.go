// Package metrics provides in-process request metrics collection.
package metrics

import (
	"math"
	"sort"
	"sync"
	"time"
)

// RequestRecord captures the result of a single HTTP request.
type RequestRecord struct {
	Endpoint            string
	Method              string
	StatusCode          int
	LatencyMs           float64
	RetryCount          int    // x-envoy-attempt-count - 1
	IdempotencyReplay   bool
	Timeout             bool
	AuthFailed          bool
	TraceID             string
	TraceparentSent     bool
	TraceparentReceived bool
	CanaryVersion       string
	EnvoyUpstreamMs     float64
	EnvoyAttemptCount   int
	ViaIstio            bool
}

// LatencyStats tracks latency samples and computes percentiles.
type LatencyStats struct {
	samples []float64
}

func (l *LatencyStats) Record(ms float64) {
	l.samples = append(l.samples, ms)
}

func (l *LatencyStats) Percentile(pct float64) float64 {
	if len(l.samples) == 0 {
		return 0
	}
	sorted := make([]float64, len(l.samples))
	copy(sorted, l.samples)
	sort.Float64s(sorted)
	idx := int(math.Floor(float64(len(sorted)) * pct / 100.0))
	if idx >= len(sorted) {
		idx = len(sorted) - 1
	}
	return sorted[idx]
}

func (l *LatencyStats) P50() float64 { return l.Percentile(50) }
func (l *LatencyStats) P95() float64 { return l.Percentile(95) }
func (l *LatencyStats) P99() float64 { return l.Percentile(99) }

func (l *LatencyStats) Mean() float64 {
	if len(l.samples) == 0 {
		return 0
	}
	sum := 0.0
	for _, s := range l.samples {
		sum += s
	}
	return sum / float64(len(l.samples))
}

func (l *LatencyStats) Count() int { return len(l.samples) }

// EndpointMetrics tracks all metrics for a single endpoint.
type EndpointMetrics struct {
	Endpoint        string
	Latency         LatencyStats
	Total           int
	Success         int // 2xx
	ClientError     int // 4xx
	ServerError     int // 5xx
	Timeout         int
	Retried         int // requests where attempt_count > 1
	RetryTotal      int // sum of extra attempts
	IdempotencyHits int
	AuthFailures    int
	StatusCodes     map[int]int
	CanaryHits      map[string]int
	TraceSent       int
	TraceReceived   int
	ViaIstio        int
}

func newEndpointMetrics(endpoint string) *EndpointMetrics {
	return &EndpointMetrics{
		Endpoint:    endpoint,
		StatusCodes: make(map[int]int),
		CanaryHits:  make(map[string]int),
	}
}

func (e *EndpointMetrics) Record(r RequestRecord) {
	e.Total++
	e.Latency.Record(r.LatencyMs)
	e.StatusCodes[r.StatusCode]++

	switch {
	case r.StatusCode >= 200 && r.StatusCode < 300:
		e.Success++
	case r.StatusCode >= 400 && r.StatusCode < 500:
		e.ClientError++
		if r.AuthFailed {
			e.AuthFailures++
		}
	case r.StatusCode >= 500:
		e.ServerError++
	}

	if r.Timeout {
		e.Timeout++
	}
	if r.IdempotencyReplay {
		e.IdempotencyHits++
	}
	if r.EnvoyAttemptCount > 1 {
		e.Retried++
		e.RetryTotal += r.EnvoyAttemptCount - 1
	}
	if r.CanaryVersion != "" {
		e.CanaryHits[r.CanaryVersion]++
	}
	if r.TraceparentSent {
		e.TraceSent++
	}
	if r.TraceparentReceived {
		e.TraceReceived++
	}
	if r.ViaIstio {
		e.ViaIstio++
	}
}

func (e *EndpointMetrics) ErrorRate() float64 {
	if e.Total == 0 {
		return 0
	}
	return float64(e.ClientError+e.ServerError+e.Timeout) / float64(e.Total)
}

func (e *EndpointMetrics) SuccessRate() float64 {
	if e.Total == 0 {
		return 0
	}
	return float64(e.Success) / float64(e.Total)
}

func (e *EndpointMetrics) TimeoutRate() float64 {
	if e.Total == 0 {
		return 0
	}
	return float64(e.Timeout) / float64(e.Total)
}

func (e *EndpointMetrics) AvgAttemptCount() float64 {
	if e.Total == 0 {
		return 1.0
	}
	return 1.0 + float64(e.RetryTotal)/float64(e.Total)
}

func (e *EndpointMetrics) TracePropagationRate() float64 {
	if e.TraceSent == 0 {
		return 0
	}
	return float64(e.TraceReceived) / float64(e.TraceSent)
}

// Collector is the global in-process metrics store.
type Collector struct {
	mu           sync.Mutex
	endpoints    map[string]*EndpointMetrics
	startTime    time.Time
	totalRecords int
}

// New creates a Collector.
func New() *Collector {
	return &Collector{
		endpoints: make(map[string]*EndpointMetrics),
		startTime: time.Now(),
	}
}

// Record records a single request result.
func (c *Collector) Record(r RequestRecord) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if _, ok := c.endpoints[r.Endpoint]; !ok {
		c.endpoints[r.Endpoint] = newEndpointMetrics(r.Endpoint)
	}
	c.endpoints[r.Endpoint].Record(r)
	c.totalRecords++
}

// ElapsedSeconds returns seconds since collection started.
func (c *Collector) ElapsedSeconds() float64 {
	return time.Since(c.startTime).Seconds()
}

// RPS returns average requests per second since collection started.
func (c *Collector) RPS() float64 {
	c.mu.Lock()
	defer c.mu.Unlock()
	elapsed := c.ElapsedSeconds()
	if elapsed <= 0 {
		return 0
	}
	return float64(c.totalRecords) / elapsed
}

// Total returns total requests recorded.
func (c *Collector) Total() int {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.totalRecords
}

// Snapshot returns a copy of the endpoint metrics map.
func (c *Collector) Snapshot() map[string]*EndpointMetrics {
	c.mu.Lock()
	defer c.mu.Unlock()
	out := make(map[string]*EndpointMetrics, len(c.endpoints))
	for k, v := range c.endpoints {
		clone := *v
		clone.StatusCodes = make(map[int]int, len(v.StatusCodes))
		for sc, cnt := range v.StatusCodes {
			clone.StatusCodes[sc] = cnt
		}
		clone.CanaryHits = make(map[string]int, len(v.CanaryHits))
		for cv, cnt := range v.CanaryHits {
			clone.CanaryHits[cv] = cnt
		}
		latCopy := make([]float64, len(v.Latency.samples))
		copy(latCopy, v.Latency.samples)
		clone.Latency = LatencyStats{samples: latCopy}
		out[k] = &clone
	}
	return out
}

// GlobalErrorRate returns the aggregate error rate across all endpoints.
func (c *Collector) GlobalErrorRate() float64 {
	snap := c.Snapshot()
	total, errors := 0, 0
	for _, m := range snap {
		total += m.Total
		errors += m.ClientError + m.ServerError + m.Timeout
	}
	if total == 0 {
		return 0
	}
	return float64(errors) / float64(total)
}

// GlobalP99 returns the 99th percentile latency across all endpoints.
func (c *Collector) GlobalP99() float64 {
	snap := c.Snapshot()
	var all []float64
	for _, m := range snap {
		all = append(all, m.Latency.samples...)
	}
	if len(all) == 0 {
		return 0
	}
	sort.Float64s(all)
	idx := int(float64(len(all)) * 0.99)
	if idx >= len(all) {
		idx = len(all) - 1
	}
	return all[idx]
}

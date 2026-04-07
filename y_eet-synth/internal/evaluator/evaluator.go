// Package evaluator implements pass/fail evaluation of collected metrics.
package evaluator

import (
	"fmt"

	"y_eet-synth/internal/config"
	"y_eet-synth/internal/metrics"
)

// Verdict is the overall evaluation outcome.
type Verdict string

const (
	VerdictPass             Verdict = "PASS"
	VerdictWarn             Verdict = "WARN"
	VerdictFail             Verdict = "FAIL"
	VerdictInsufficientData Verdict = "INSUFFICIENT_DATA"
)

// CheckVerdict is the result of a single threshold check.
type CheckVerdict string

const (
	CheckPass CheckVerdict = "PASS"
	CheckWarn CheckVerdict = "WARN"
	CheckFail CheckVerdict = "FAIL"
)

// Check is the result of one threshold check.
type Check struct {
	Name      string       `json:"name"`
	Verdict   CheckVerdict `json:"verdict"`
	Message   string       `json:"message"`
	Observed  float64      `json:"observed,omitempty"`
	Threshold float64      `json:"threshold,omitempty"`
	Unit      string       `json:"unit,omitempty"`
}

// MeshCheckStatus represents a mesh validation check outcome.
type MeshCheckStatus string

const (
	MeshPass MeshCheckStatus = "PASS"
	MeshWarn MeshCheckStatus = "WARN"
	MeshFail MeshCheckStatus = "FAIL"
	MeshSkip MeshCheckStatus = "SKIP"
)

// MeshResult is the result of one mesh validation check.
type MeshResult struct {
	Name    string          `json:"name"`
	Status  MeshCheckStatus `json:"status"`
	Message string          `json:"message"`
	Details map[string]interface{} `json:"details,omitempty"`
}

// ChaosResult is the result of one chaos scenario.
type ChaosResult struct {
	Scenario       string `json:"scenario"`
	Passed         bool   `json:"passed"`
	ExpectedStatus int    `json:"expected_status"`
	StatusCode     int    `json:"status_code"`
	Note           string `json:"note,omitempty"`
}

// Result is the final evaluation output.
type Result struct {
	Verdict    Verdict  `json:"verdict"`
	ExitCode   int      `json:"exit_code"`
	Confidence float64  `json:"confidence"`
	Checks     []Check  `json:"checks"`
}

func (r *Result) Fails() []Check {
	var out []Check
	for _, c := range r.Checks {
		if c.Verdict == CheckFail {
			out = append(out, c)
		}
	}
	return out
}

func (r *Result) Warns() []Check {
	var out []Check
	for _, c := range r.Checks {
		if c.Verdict == CheckWarn {
			out = append(out, c)
		}
	}
	return out
}

// Evaluator runs threshold checks against collected metrics.
type Evaluator struct {
	t config.ThresholdConfig
}

// New creates an Evaluator.
func New(t config.ThresholdConfig) *Evaluator {
	return &Evaluator{t: t}
}

// Evaluate produces a Result from the collected metrics and optional mesh/chaos outcomes.
func (e *Evaluator) Evaluate(
	m *metrics.Collector,
	meshResults []MeshResult,
	chaosResults []ChaosResult,
) Result {
	snap := m.Snapshot()
	total := 0
	for _, em := range snap {
		total += em.Total
	}

	if total < 10 {
		return Result{
			Verdict:    VerdictInsufficientData,
			ExitCode:   3,
			Confidence: 0,
		}
	}

	confidence := float64(total) / 10.0
	if confidence > 100 {
		confidence = 100
	}

	result := Result{
		Verdict:    VerdictPass,
		Confidence: confidence,
	}

	// Global error rate
	errRate := m.GlobalErrorRate()
	result.Checks = append(result.Checks, Check{
		Name: "global_error_rate",
		Verdict: check(errRate > e.t.MaxErrorRate, errRate > e.t.MaxErrorRate/2),
		Message: fmt.Sprintf("error rate %.2f%% vs threshold %.2f%%",
			errRate*100, e.t.MaxErrorRate*100),
		Observed:  errRate * 100,
		Threshold: e.t.MaxErrorRate * 100,
		Unit:      "%",
	})

	// Global p99 latency
	p99 := m.GlobalP99()
	result.Checks = append(result.Checks, Check{
		Name: "global_p99_latency",
		Verdict: func() CheckVerdict {
			if p99 > e.t.P99LatencyMs {
				return CheckFail
			}
			if p99 > e.t.P95LatencyMs {
				return CheckWarn
			}
			return CheckPass
		}(),
		Message: fmt.Sprintf("p99 %.0fms vs threshold %.0fms", p99, e.t.P99LatencyMs),
		Observed:  p99,
		Threshold: e.t.P99LatencyMs,
		Unit:      "ms",
	})

	// Per-endpoint checks
	for epName, em := range snap {
		if em.Total < 5 {
			continue
		}

		// Timeout rate
		if em.TimeoutRate() > e.t.MaxTimeoutRate {
			result.Checks = append(result.Checks, Check{
				Name:    "timeout_rate:" + epName,
				Verdict: CheckWarn,
				Message: fmt.Sprintf("%s: timeout rate %.2f%% > threshold", epName,
					em.TimeoutRate()*100),
				Observed:  em.TimeoutRate() * 100,
				Threshold: e.t.MaxTimeoutRate * 100,
				Unit:      "%",
			})
		}

		// Auth failure rate
		if em.Total > 0 {
			authRate := float64(em.AuthFailures) / float64(em.Total)
			if authRate > e.t.MaxAuthFailureRate {
				result.Checks = append(result.Checks, Check{
					Name:    "auth_failure_rate:" + epName,
					Verdict: CheckWarn,
					Message: fmt.Sprintf("%s: auth failure rate %.2f%%", epName, authRate*100),
					Observed:  authRate * 100,
					Threshold: e.t.MaxAuthFailureRate * 100,
					Unit:      "%",
				})
			}
		}

		// Retry amplification
		if em.AvgAttemptCount() > e.t.RetryAmplificationThreshold {
			result.Checks = append(result.Checks, Check{
				Name:    "retry_amplification:" + epName,
				Verdict: CheckWarn,
				Message: fmt.Sprintf("%s: avg attempt count %.2f > threshold %.1f",
					epName, em.AvgAttemptCount(), e.t.RetryAmplificationThreshold),
				Observed:  em.AvgAttemptCount(),
				Threshold: e.t.RetryAmplificationThreshold,
			})
		}

		// Trace propagation
		if em.TraceSent > 10 && em.TracePropagationRate() < e.t.MinTracePropagationRate {
			result.Checks = append(result.Checks, Check{
				Name:    "trace_propagation:" + epName,
				Verdict: CheckWarn,
				Message: fmt.Sprintf("%s: trace propagation %.0f%% < threshold %.0f%%",
					epName, em.TracePropagationRate()*100, e.t.MinTracePropagationRate*100),
				Observed:  em.TracePropagationRate() * 100,
				Threshold: e.t.MinTracePropagationRate * 100,
				Unit:      "%",
			})
		}
	}

	// Mesh results
	for _, mr := range meshResults {
		if mr.Status == MeshSkip {
			continue
		}
		v := CheckPass
		if mr.Status == MeshFail {
			v = CheckFail
		} else if mr.Status == MeshWarn {
			v = CheckWarn
		}
		result.Checks = append(result.Checks, Check{
			Name:    "mesh:" + mr.Name,
			Verdict: v,
			Message: mr.Message,
		})
	}

	// Chaos results
	for _, cr := range chaosResults {
		v := CheckPass
		if !cr.Passed {
			v = CheckFail
		}
		msg := cr.Note
		if msg == "" {
			msg = fmt.Sprintf("expected %d, got %d", cr.ExpectedStatus, cr.StatusCode)
		}
		result.Checks = append(result.Checks, Check{
			Name:      "chaos:" + cr.Scenario,
			Verdict:   v,
			Message:   msg,
			Observed:  float64(cr.StatusCode),
			Threshold: float64(cr.ExpectedStatus),
		})
	}

	// Final verdict
	hasFail := false
	hasWarn := false
	for _, c := range result.Checks {
		if c.Verdict == CheckFail {
			hasFail = true
		}
		if c.Verdict == CheckWarn {
			hasWarn = true
		}
	}
	switch {
	case hasFail:
		result.Verdict = VerdictFail
		result.ExitCode = 1
	case hasWarn:
		result.Verdict = VerdictWarn
		result.ExitCode = 2
	default:
		result.Verdict = VerdictPass
		result.ExitCode = 0
	}

	return result
}

func check(fail, _ bool) CheckVerdict {
	if fail {
		return CheckFail
	}
	return CheckPass
}

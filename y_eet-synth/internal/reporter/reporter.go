// Package reporter formats and writes run results to the terminal and a JSON file.
package reporter

import (
	"encoding/json"
	"fmt"
	"os"
	"sort"
	"strings"
	"time"

	"y_eet-synth/internal/evaluator"
	"y_eet-synth/internal/metrics"
)

const (
	colorReset  = "\033[0m"
	colorRed    = "\033[31m"
	colorGreen  = "\033[32m"
	colorYellow = "\033[33m"
	colorCyan   = "\033[36m"
	colorBold   = "\033[1m"
	colorDim    = "\033[2m"
)

func bold(s string) string    { return colorBold + s + colorReset }
func green(s string) string   { return colorGreen + s + colorReset }
func yellow(s string) string  { return colorYellow + s + colorReset }
func red(s string) string     { return colorRed + s + colorReset }
func cyan(s string) string    { return colorCyan + s + colorReset }
func dim(s string) string     { return colorDim + s + colorReset }

// PrintSummary renders a formatted run summary to stdout.
func PrintSummary(
	m *metrics.Collector,
	meshResults []evaluator.MeshResult,
	eval *evaluator.Result,
) {
	snap := m.Snapshot()

	fmt.Println()
	fmt.Println(bold("━━━  Yeet Platform — Synthetic Traffic Report"))
	fmt.Printf("     %d total requests · %.1f rps average · %.1fs elapsed\n\n",
		m.Total(), m.RPS(), m.ElapsedSeconds())

	// Endpoint table
	fmt.Println(bold("Endpoint Metrics"))
	fmt.Printf("  %-44s %6s %9s %6s %6s %6s %8s %8s\n",
		"Endpoint", "Reqs", "Success%", "p50ms", "p95ms", "p99ms", "Timeouts", "Retried")
	fmt.Println(strings.Repeat("─", 100))

	epNames := make([]string, 0, len(snap))
	for k := range snap {
		epNames = append(epNames, k)
	}
	sort.Strings(epNames)

	for _, name := range epNames {
		em := snap[name]
		sr := em.SuccessRate()
		srStr := fmt.Sprintf("%.1f%%", sr*100)
		var srColored string
		switch {
		case sr >= 0.99:
			srColored = green(srStr)
		case sr >= 0.95:
			srColored = yellow(srStr)
		default:
			srColored = red(srStr)
		}
		fmt.Printf("  %-44s %6d %9s %6.0f %6.0f %6.0f %8d %8d\n",
			truncate(name, 44),
			em.Total,
			srColored,
			em.Latency.P50(),
			em.Latency.P95(),
			em.Latency.P99(),
			em.Timeout,
			em.Retried,
		)
	}
	fmt.Println()

	// Status code breakdown
	fmt.Println(bold("Status Code Distribution"))
	fmt.Printf("  %-44s %6s %6s %6s %10s\n", "Endpoint", "2xx", "4xx", "5xx", "Timeout")
	fmt.Println(strings.Repeat("─", 80))
	for _, name := range epNames {
		em := snap[name]
		fmt.Printf("  %-44s %6d %6d %6d %10d\n",
			truncate(name, 44),
			em.Success, em.ClientError, em.ServerError, em.Timeout)
	}
	fmt.Println()

	// Mesh results
	if len(meshResults) > 0 {
		fmt.Println(bold("Mesh Validation"))
		fmt.Printf("  %-30s %8s  %s\n", "Check", "Status", "Message")
		fmt.Println(strings.Repeat("─", 80))
		for _, mr := range meshResults {
			statusStr := string(mr.Status)
			switch mr.Status {
			case evaluator.MeshPass:
				statusStr = green(statusStr)
			case evaluator.MeshFail:
				statusStr = red(statusStr)
			case evaluator.MeshWarn:
				statusStr = yellow(statusStr)
			default:
				statusStr = dim(statusStr)
			}
			fmt.Printf("  %-30s %8s  %s\n",
				strings.ReplaceAll(mr.Name, "_", " "),
				statusStr,
				mr.Message)
		}
		fmt.Println()
	}

	// Evaluation
	if eval != nil {
		printEvaluation(eval)
	}
}

func printEvaluation(ev *evaluator.Result) {
	verdictStr := string(ev.Verdict)
	switch ev.Verdict {
	case evaluator.VerdictPass:
		verdictStr = green(verdictStr)
	case evaluator.VerdictWarn:
		verdictStr = yellow(verdictStr)
	case evaluator.VerdictFail:
		verdictStr = red(verdictStr)
	default:
		verdictStr = dim(verdictStr)
	}

	fmt.Println(bold("Evaluation"))
	fmt.Printf("  Verdict: %s  confidence=%.0f%%  exit_code=%d  fails=%d  warns=%d\n",
		verdictStr, ev.Confidence, ev.ExitCode,
		len(ev.Fails()), len(ev.Warns()))
	fmt.Println()

	fmt.Printf("  %-50s %8s  %s\n", "Check", "Verdict", "Detail")
	fmt.Println(strings.Repeat("─", 90))
	for _, c := range ev.Checks {
		vStr := string(c.Verdict)
		switch c.Verdict {
		case evaluator.CheckPass:
			vStr = green(vStr)
		case evaluator.CheckFail:
			vStr = red(vStr)
		case evaluator.CheckWarn:
			vStr = yellow(vStr)
		}
		detail := c.Message
		if c.Observed != 0 || c.Threshold != 0 {
			detail = fmt.Sprintf("%s  (%.2f%s / %.2f%s)",
				c.Message, c.Observed, c.Unit, c.Threshold, c.Unit)
		}
		fmt.Printf("  %-50s %8s  %s\n",
			truncate(c.Name, 50), vStr, detail)
	}
	fmt.Println()
}

// WriteJSONReport serialises all run data to the configured file path.
func WriteJSONReport(
	path string,
	m *metrics.Collector,
	meshResults []evaluator.MeshResult,
	eval *evaluator.Result,
	chaosResults []evaluator.ChaosResult,
) error {
	snap := m.Snapshot()

	type endpointJSON struct {
		Total               int                `json:"total"`
		SuccessRatePct      float64            `json:"success_rate_pct"`
		ErrorRatePct        float64            `json:"error_rate_pct"`
		P50Ms               float64            `json:"p50_ms"`
		P95Ms               float64            `json:"p95_ms"`
		P99Ms               float64            `json:"p99_ms"`
		Timeouts            int                `json:"timeouts"`
		Retried             int                `json:"retried"`
		AvgAttemptCount     float64            `json:"avg_attempt_count"`
		IdempotencyHits     int                `json:"idempotency_hits"`
		AuthFailures        int                `json:"auth_failures"`
		ViaIstioPct         float64            `json:"via_istio_pct"`
		StatusCodes         map[int]int        `json:"status_codes"`
		CanaryDistribution  map[string]int     `json:"canary_distribution"`
		TracePropagationPct float64            `json:"trace_propagation_rate_pct"`
	}

	endpoints := make(map[string]endpointJSON, len(snap))
	for name, em := range snap {
		istioPct := 0.0
		if em.Total > 0 {
			istioPct = float64(em.ViaIstio) / float64(em.Total) * 100
		}
		endpoints[name] = endpointJSON{
			Total:               em.Total,
			SuccessRatePct:      round2(em.SuccessRate() * 100),
			ErrorRatePct:        round2(em.ErrorRate() * 100),
			P50Ms:               round1(em.Latency.P50()),
			P95Ms:               round1(em.Latency.P95()),
			P99Ms:               round1(em.Latency.P99()),
			Timeouts:            em.Timeout,
			Retried:             em.Retried,
			AvgAttemptCount:     round3(em.AvgAttemptCount()),
			IdempotencyHits:     em.IdempotencyHits,
			AuthFailures:        em.AuthFailures,
			ViaIstioPct:         round1(istioPct),
			StatusCodes:         em.StatusCodes,
			CanaryDistribution:  em.CanaryHits,
			TracePropagationPct: round1(em.TracePropagationRate() * 100),
		}
	}

	report := map[string]interface{}{
		"generated_at":          time.Now().UTC().Format(time.RFC3339),
		"duration_seconds":      round2(m.ElapsedSeconds()),
		"total_requests":        m.Total(),
		"rps_average":           round2(m.RPS()),
		"global_error_rate_pct": round2(m.GlobalErrorRate() * 100),
		"global_p99_ms":         round1(m.GlobalP99()),
		"endpoints":             endpoints,
		"mesh":                  meshResults,
		"chaos":                 chaosResults,
		"evaluation":            eval,
	}

	data, err := json.MarshalIndent(report, "", "  ")
	if err != nil {
		return fmt.Errorf("marshal report: %w", err)
	}
	if err := os.WriteFile(path, data, 0o644); err != nil {
		return fmt.Errorf("write report: %w", err)
	}
	fmt.Printf("\n%s JSON report written to %s\n", dim("·"), cyan(path))
	return nil
}

// ── Helpers ───────────────────────────────────────────────────────────────────

func truncate(s string, n int) string {
	if len(s) <= n {
		return s
	}
	return s[:n-1] + "…"
}

func round1(f float64) float64 { return float64(int(f*10+0.5)) / 10 }
func round2(f float64) float64 { return float64(int(f*100+0.5)) / 100 }
func round3(f float64) float64 { return float64(int(f*1000+0.5)) / 1000 }

// y_eet-synth — Yeet Platform synthetic traffic generator and service mesh validator.
//
// Usage:
//
//	y_eet-synth smoke
//	y_eet-synth run --profile normal --duration 300
//	y_eet-synth mesh --validate-all
//	y_eet-synth canary --expected-version canary --expected-weight 0.10
//	y_eet-synth chaos --duration 180
//	y_eet-synth trace --sample-size 200
//	y_eet-synth retry --duration 60
//	y_eet-synth list-profiles
package main

import (
	"context"
	"fmt"
	"log"
	"os"
	"sort"
	"strings"

	"github.com/spf13/cobra"

	"y_eet-synth/internal/chaos"
	"y_eet-synth/internal/client"
	"y_eet-synth/internal/config"
	"y_eet-synth/internal/evaluator"
	"y_eet-synth/internal/mesh"
	"y_eet-synth/internal/metrics"
	"y_eet-synth/internal/profiles"
	"y_eet-synth/internal/reporter"
	"y_eet-synth/internal/runner"
	"y_eet-synth/internal/token"
)

// runArgs holds the common flags shared by all traffic commands.
type runArgs struct {
	configPath string
	baseURL    string
	logLevel   string
	noTLS      bool
	jsonReport string
}

func addCommonFlags(cmd *cobra.Command, args *runArgs) {
	cmd.Flags().StringVar(&args.configPath, "config", "", "Path to YAML config file (env: SYNTH_CONFIG)")
	cmd.Flags().StringVar(&args.baseURL, "base-url", "", "API base URL (env: SYNTH_BASE_URL)")
	cmd.Flags().StringVar(&args.logLevel, "log-level", "INFO", "Log verbosity: DEBUG|INFO|WARNING|ERROR")
	cmd.Flags().BoolVar(&args.noTLS, "no-tls-verify", false, "Disable TLS certificate verification")
	cmd.Flags().StringVar(&args.jsonReport, "json-report", "", "Write JSON report to this path (env: SYNTH_JSON_REPORT)")
}

func loadCfg(args runArgs) (*config.Config, error) {
	cfg, err := config.Load(args.configPath)
	if err != nil {
		return nil, fmt.Errorf("load config: %w", err)
	}
	if args.baseURL != "" {
		cfg.BaseURL = args.baseURL
	}
	if args.noTLS {
		cfg.TLSVerify = false
	}
	if args.jsonReport != "" {
		cfg.JSONReportPath = args.jsonReport
	}
	return cfg, nil
}

// runTraffic executes the full traffic generation + optional validation pipeline.
func runTraffic(
	cfg *config.Config,
	runMesh bool,
	runChaos bool,
) int {
	ctx := context.Background()

	m := metrics.New()

	cl := client.New(client.Options{
		BaseURL:               cfg.BaseURL,
		InternalBaseURL:       cfg.InternalBaseURL,
		Metrics:               m,
		RequestTimeoutSeconds: cfg.RequestTimeoutSeconds,
		TLSVerify:             cfg.TLSVerify,
		XSynthetic:            cfg.XSynthetic,
		MaxIdleConns:          cfg.Profile.Concurrency * 2,
	})

	pool := token.New(cfg.BaseURL, cfg.TokenPoolSize, cfg.SeedAdminUser)
	pool.Seed(ctx)

	r := runner.New(cl, pool, m, cfg.Profile)
	r.Run(ctx)

	// Mesh validation
	var meshResults []evaluator.MeshResult
	if runMesh || cfg.Profile.MeshValidation {
		log.Println("[main] running mesh validation...")
		v := mesh.New(cfg)
		meshResults = v.RunAll(ctx, cl, pool)
	}

	// Chaos injection
	var chaosResults []evaluator.ChaosResult
	if runChaos || cfg.Profile.ChaosEnabled {
		log.Println("[main] running chaos scenarios...")
		inj := chaos.New(cl, pool)
		chaosResults = inj.RunAll(ctx)
	}

	// Evaluate
	ev := evaluator.New(cfg.Thresholds)
	result := ev.Evaluate(m, meshResults, chaosResults)

	// Report
	reporter.PrintSummary(m, meshResults, &result)
	if err := reporter.WriteJSONReport(cfg.JSONReportPath, m, meshResults, &result, chaosResults); err != nil {
		log.Printf("[main] WARNING: could not write JSON report: %v", err)
	}

	return result.ExitCode
}

// ── Commands ──────────────────────────────────────────────────────────────────

func newSmokeCmd() *cobra.Command {
	var args runArgs
	cmd := &cobra.Command{
		Use:   "smoke",
		Short: "Quick smoke test: 30s, 5 rps, covers all endpoint categories",
		Long: `Runs a short smoke test against the platform.
Returns exit 0 if the service is healthy, 1 if failures are detected.

Example:
  y_eet-synth smoke --base-url https://api.y_eet.com`,
		RunE: func(cmd *cobra.Command, _ []string) error {
			cfg, err := loadCfg(args)
			if err != nil {
				return err
			}
			p, _ := profiles.Get("smoke")
			cfg.Profile = p
			os.Exit(runTraffic(cfg, false, false))
			return nil
		},
	}
	addCommonFlags(cmd, &args)
	return cmd
}

func newRunCmd() *cobra.Command {
	var args runArgs
	var profileName string
	var duration, concurrency int
	var rps float64

	cmd := &cobra.Command{
		Use:   "run",
		Short: "Run synthetic traffic with the specified profile",
		Long: `Generates realistic synthetic traffic for a configurable duration.

Examples:
  y_eet-synth run --profile normal --duration 300
  y_eet-synth run --profile burst --duration 180
  y_eet-synth run --profile low --rps 5`,
		RunE: func(cmd *cobra.Command, _ []string) error {
			cfg, err := loadCfg(args)
			if err != nil {
				return err
			}
			p, err := profiles.Get(profileName)
			if err != nil {
				return err
			}
			cfg.Profile = p
			if duration > 0 {
				cfg.Profile.DurationSeconds = duration
			}
			if concurrency > 0 {
				cfg.Profile.Concurrency = concurrency
			}
			if cmd.Flags().Changed("rps") {
				cfg.Profile.RPSTarget = rps
			}
			os.Exit(runTraffic(cfg, false, false))
			return nil
		},
	}
	addCommonFlags(cmd, &args)
	cmd.Flags().StringVar(&profileName, "profile", "normal", "Traffic profile: "+strings.Join(profiles.Names(), "|"))
	cmd.Flags().IntVar(&duration, "duration", 0, "Override duration in seconds")
	cmd.Flags().IntVar(&concurrency, "concurrency", 0, "Override concurrency")
	cmd.Flags().Float64Var(&rps, "rps", 0, "Override RPS target (0 = unlimited)")
	return cmd
}

func newMeshCmd() *cobra.Command {
	var args runArgs
	var validateAll bool
	var duration int

	cmd := &cobra.Command{
		Use:   "mesh",
		Short: "Istio / service mesh validation mode",
		Long: `Runs targeted mesh validation scenarios: retry, timeout, circuit breaker,
mTLS, trace propagation, and ingress routing.

Example:
  y_eet-synth mesh --validate-all --duration 120`,
		RunE: func(cmd *cobra.Command, _ []string) error {
			cfg, err := loadCfg(args)
			if err != nil {
				return err
			}
			if validateAll {
				cfg.Mesh.ValidateRetries = true
				cfg.Mesh.ValidateTimeouts = true
				cfg.Mesh.ValidateCircuitBreaker = true
				cfg.Mesh.ValidateTracePropagation = true
				cfg.Mesh.ValidateMTLS = true
				cfg.Mesh.ValidateCanary = false         // requires live canary deployment
				cfg.Mesh.ValidateFaultInjection = false // requires VirtualService config
			}
			p, _ := profiles.Get("mesh")
			cfg.Profile = p
			if duration > 0 {
				cfg.Profile.DurationSeconds = duration
			}
			os.Exit(runTraffic(cfg, true, false))
			return nil
		},
	}
	addCommonFlags(cmd, &args)
	cmd.Flags().BoolVar(&validateAll, "validate-all", false, "Enable all mesh validation checks")
	cmd.Flags().IntVar(&duration, "duration", 120, "Duration in seconds")
	return cmd
}

func newCanaryCmd() *cobra.Command {
	var args runArgs
	var expectedVersion string
	var expectedWeight, tolerance float64
	var sampleSize, duration int

	cmd := &cobra.Command{
		Use:   "canary",
		Short: "Canary rollout validation: verify traffic split matches declared weight",
		Long: `Sends traffic and validates that the canary version receives the expected fraction.

Example:
  y_eet-synth canary --expected-version v2.1.0 --expected-weight 0.20`,
		RunE: func(cmd *cobra.Command, _ []string) error {
			cfg, err := loadCfg(args)
			if err != nil {
				return err
			}
			cfg.Mesh.ValidateCanary = true
			cfg.Mesh.Canary.ExpectedVersion = expectedVersion
			cfg.Mesh.Canary.ExpectedWeight = expectedWeight
			cfg.Mesh.Canary.SplitTolerance = tolerance
			p, _ := profiles.Get("canary")
			cfg.Profile = p
			if duration > 0 {
				cfg.Profile.DurationSeconds = duration
			}
			if sampleSize > 0 {
				cfg.Profile.DurationSeconds = sampleSize / 5
				if cfg.Profile.DurationSeconds < 30 {
					cfg.Profile.DurationSeconds = 30
				}
			}
			os.Exit(runTraffic(cfg, true, false))
			return nil
		},
	}
	addCommonFlags(cmd, &args)
	cmd.Flags().StringVar(&expectedVersion, "expected-version", "canary", "Expected version header value")
	cmd.Flags().Float64Var(&expectedWeight, "expected-weight", 0.10, "Expected canary traffic fraction (0.10 = 10%)")
	cmd.Flags().Float64Var(&tolerance, "tolerance", 0.05, "Acceptable deviation from expected weight")
	cmd.Flags().IntVar(&sampleSize, "sample-size", 300, "Number of requests to sample for canary check")
	cmd.Flags().IntVar(&duration, "duration", 120, "Duration in seconds")
	return cmd
}

func newChaosCmd() *cobra.Command {
	var args runArgs
	var duration int

	cmd := &cobra.Command{
		Use:   "chaos",
		Short: "Chaos / fault-path validation mode",
		Long: `Runs fault scenarios alongside normal traffic: stale tokens, malformed
payloads, duplicate replays, and missing idempotency keys.

WARNING: Only run in staging or controlled environments.

Example:
  y_eet-synth chaos --duration 180`,
		RunE: func(cmd *cobra.Command, _ []string) error {
			cfg, err := loadCfg(args)
			if err != nil {
				return err
			}
			p, _ := profiles.Get("chaos")
			cfg.Profile = p
			if duration > 0 {
				cfg.Profile.DurationSeconds = duration
			}
			os.Exit(runTraffic(cfg, false, true))
			return nil
		},
	}
	addCommonFlags(cmd, &args)
	cmd.Flags().IntVar(&duration, "duration", 180, "Duration in seconds")
	return cmd
}

func newTraceCmd() *cobra.Command {
	var args runArgs
	var sampleSize int

	cmd := &cobra.Command{
		Use:   "trace",
		Short: "Trace propagation validation: verify W3C traceparent continuity",
		Long: `Sends requests with traceparent headers and checks that the service echoes them back.

Example:
  y_eet-synth trace --sample-size 200`,
		RunE: func(cmd *cobra.Command, _ []string) error {
			cfg, err := loadCfg(args)
			if err != nil {
				return err
			}
			cfg.Mesh.ValidateTracePropagation = true
			p, _ := profiles.Get("smoke")
			cfg.Profile = p
			dur := sampleSize / 5
			if dur < 30 {
				dur = 30
			}
			cfg.Profile.DurationSeconds = dur
			os.Exit(runTraffic(cfg, true, false))
			return nil
		},
	}
	addCommonFlags(cmd, &args)
	cmd.Flags().IntVar(&sampleSize, "sample-size", 100, "Number of requests to sample")
	return cmd
}

func newRetryCmd() *cobra.Command {
	var args runArgs
	var duration int

	cmd := &cobra.Command{
		Use:   "retry",
		Short: "Retry and timeout verification",
		Long: `Validates retry behaviour and timeout alignment via Envoy headers.

Example:
  y_eet-synth retry --duration 60`,
		RunE: func(cmd *cobra.Command, _ []string) error {
			cfg, err := loadCfg(args)
			if err != nil {
				return err
			}
			cfg.Mesh.ValidateRetries = true
			cfg.Mesh.ValidateTimeouts = true
			p, _ := profiles.Get("mesh")
			cfg.Profile = p
			if duration > 0 {
				cfg.Profile.DurationSeconds = duration
			}
			os.Exit(runTraffic(cfg, true, false))
			return nil
		},
	}
	addCommonFlags(cmd, &args)
	cmd.Flags().IntVar(&duration, "duration", 60, "Duration in seconds")
	return cmd
}

func newListProfilesCmd() *cobra.Command {
	return &cobra.Command{
		Use:   "list-profiles",
		Short: "List all available traffic profiles",
		RunE: func(cmd *cobra.Command, _ []string) error {
			names := profiles.Names()
			sort.Strings(names)
			fmt.Printf("  %-14s %12s %8s %10s  %s\n",
				"Profile", "Concurrency", "RPS", "Duration", "Notes")
			fmt.Println(strings.Repeat("─", 65))
			for _, name := range names {
				p := profiles.All[name]
				notes := ""
				if p.ChaosEnabled {
					notes += "[chaos] "
				}
				if p.MeshValidation {
					notes += "[mesh] "
				}
				if p.CanaryValidation {
					notes += "[canary] "
				}
				if p.BurstFactor > 1 {
					notes += fmt.Sprintf("[burst %.1fx] ", p.BurstFactor)
				}
				fmt.Printf("  %-14s %12d %8.1f %9ds  %s\n",
					name, p.Concurrency, p.RPSTarget, p.DurationSeconds, notes)
			}
			return nil
		},
	}
}

// ── Root ──────────────────────────────────────────────────────────────────────

func main() {
	root := &cobra.Command{
		Use:   "y_eet-synth",
		Short: "Yeet Platform synthetic traffic generator and service mesh validator",
		Long: `y_eet-synth generates realistic synthetic traffic for the Yeet crypto-casino platform.
It validates API behaviour, Istio mesh policies, chaos resilience, and canary rollouts.

Exit codes:
  0  — all checks passed
  1  — one or more FAIL checks
  2  — all checks passed but WARNs present
  3  — insufficient data for evaluation`,
	}

	root.AddCommand(
		newSmokeCmd(),
		newRunCmd(),
		newMeshCmd(),
		newCanaryCmd(),
		newChaosCmd(),
		newTraceCmd(),
		newRetryCmd(),
		newListProfilesCmd(),
	)

	if err := root.Execute(); err != nil {
		os.Exit(1)
	}
}

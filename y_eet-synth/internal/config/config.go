// Package config provides configuration types and loading logic for y_eet-synth.
// Configuration is read from an optional YAML file with environment variable overrides.
package config

import (
	"os"
	"strconv"
	"strings"

	"gopkg.in/yaml.v3"
)

// ThresholdConfig holds pass/fail thresholds for the evaluator.
type ThresholdConfig struct {
	MaxErrorRate                float64 `yaml:"max_error_rate"`
	P95LatencyMs                float64 `yaml:"p95_latency_ms"`
	P99LatencyMs                float64 `yaml:"p99_latency_ms"`
	MaxTimeoutRate              float64 `yaml:"max_timeout_rate"`
	MaxAuthFailureRate          float64 `yaml:"max_auth_failure_rate"`
	CanarySplitTolerance        float64 `yaml:"canary_split_tolerance"`
	MinTracePropagationRate     float64 `yaml:"min_trace_propagation_rate"`
	RetryAmplificationThreshold float64 `yaml:"retry_amplification_threshold"`
}

func defaultThresholds() ThresholdConfig {
	return ThresholdConfig{
		MaxErrorRate:                0.02,
		P95LatencyMs:                800.0,
		P99LatencyMs:                2000.0,
		MaxTimeoutRate:              0.005,
		MaxAuthFailureRate:          0.01,
		CanarySplitTolerance:        0.05,
		MinTracePropagationRate:     0.95,
		RetryAmplificationThreshold: 1.5,
	}
}

// ScenarioWeights maps scenario name to its relative weight.
type ScenarioWeights map[string]float64

// ProfileConfig describes how the traffic runner should behave.
type ProfileConfig struct {
	Name                  string          `yaml:"name"`
	Concurrency           int             `yaml:"concurrency"`
	DurationSeconds       int             `yaml:"duration_seconds"`
	RPSTarget             float64         `yaml:"rps_target"`
	BurstFactor           float64         `yaml:"burst_factor"`
	BurstDurationSeconds  int             `yaml:"burst_duration_seconds"`
	BurstIntervalSeconds  int             `yaml:"burst_interval_seconds"`
	ChaosEnabled          bool            `yaml:"chaos_enabled"`
	MeshValidation        bool            `yaml:"mesh_validation"`
	CanaryValidation      bool            `yaml:"canary_validation"`
	ScenarioWeights       ScenarioWeights `yaml:"scenario_weights"`
}

// CanaryConfig describes canary split validation parameters.
type CanaryConfig struct {
	HeaderName      string  `yaml:"header_name"`
	ExpectedVersion string  `yaml:"expected_version"`
	ExpectedWeight  float64 `yaml:"expected_weight"`
	SplitTolerance  float64 `yaml:"split_tolerance"`
}

func defaultCanary() CanaryConfig {
	return CanaryConfig{
		HeaderName:      "x-canary-version",
		ExpectedVersion: "canary",
		ExpectedWeight:  0.10,
		SplitTolerance:  0.05,
	}
}

// MeshConfig controls which Istio validation checks are active.
type MeshConfig struct {
	ValidateRetries          bool         `yaml:"validate_retries"`
	ValidateTimeouts         bool         `yaml:"validate_timeouts"`
	ValidateCircuitBreaker   bool         `yaml:"validate_circuit_breaker"`
	ValidateCanary           bool         `yaml:"validate_canary"`
	ValidateFaultInjection   bool         `yaml:"validate_fault_injection"`
	ValidateTracePropagation bool         `yaml:"validate_trace_propagation"`
	ValidateMTLS             bool         `yaml:"validate_mtls"`
	Canary                   CanaryConfig `yaml:"canary"`
	CircuitBreakerFloodRPS   float64      `yaml:"circuit_breaker_flood_rps"`
	CircuitBreakerFloodDur   int          `yaml:"circuit_breaker_flood_duration"`
	TimeoutProbeDelayMs      int          `yaml:"timeout_probe_delay_ms"`
	FaultAbortPct            int          `yaml:"fault_abort_pct"`
}

func defaultMesh() MeshConfig {
	return MeshConfig{
		ValidateRetries:          true,
		ValidateTimeouts:         true,
		ValidateCircuitBreaker:   true,
		ValidateCanary:           false,
		ValidateFaultInjection:   false,
		ValidateTracePropagation: true,
		ValidateMTLS:             true,
		Canary:                   defaultCanary(),
		CircuitBreakerFloodRPS:   200.0,
		CircuitBreakerFloodDur:   10,
		TimeoutProbeDelayMs:      500,
		FaultAbortPct:            30,
	}
}

// Config is the root configuration object.
type Config struct {
	BaseURL               string  `yaml:"base_url"`
	InternalBaseURL       string  `yaml:"internal_base_url"`
	ServiceName           string  `yaml:"service_name"`
	Environment           string  `yaml:"environment"`
	OTELEndpoint          string  `yaml:"otel_endpoint"`
	OTELEnabled           bool    `yaml:"otel_enabled"`
	LogLevel              string  `yaml:"log_level"`
	RequestTimeoutSeconds float64 `yaml:"request_timeout_seconds"`
	ConnectTimeoutSeconds float64 `yaml:"connect_timeout_seconds"`
	TLSVerify             bool    `yaml:"tls_verify"`
	XSynthetic            bool    `yaml:"x_synthetic"`
	TokenPoolSize         int     `yaml:"token_pool_size"`
	SeedAdminUser         bool    `yaml:"seed_admin_user"`
	JSONReportPath        string  `yaml:"json_report_path"`

	Profile    ProfileConfig    `yaml:"profile"`
	Thresholds ThresholdConfig  `yaml:"thresholds"`
	Mesh       MeshConfig       `yaml:"mesh"`
}

// Default returns a Config populated with sensible defaults.
func Default() *Config {
	return &Config{
		BaseURL:               "http://localhost:8080",
		InternalBaseURL:       "http://localhost:8080",
		ServiceName:           "y_eet-synth",
		Environment:           "local",
		OTELEndpoint:          "http://localhost:4317",
		OTELEnabled:           true,
		LogLevel:              "INFO",
		RequestTimeoutSeconds: 30.0,
		ConnectTimeoutSeconds: 5.0,
		TLSVerify:             true,
		XSynthetic:            true,
		TokenPoolSize:         20,
		SeedAdminUser:         true,
		JSONReportPath:        "report.json",
		Profile: ProfileConfig{
			Name:            "normal",
			Concurrency:     20,
			DurationSeconds: 60,
			RPSTarget:       50.0,
			ScenarioWeights: ScenarioWeights{
				"anonymous":    0.10,
				"authenticated": 0.25,
				"active_bettor": 0.45,
				"wallet_heavy": 0.15,
				"admin":        0.05,
			},
		},
		Thresholds: defaultThresholds(),
		Mesh:       defaultMesh(),
	}
}

// yamlFile is used for partial YAML unmarshaling.
type yamlFile struct {
	BaseURL               string          `yaml:"base_url"`
	InternalBaseURL       string          `yaml:"internal_base_url"`
	ServiceName           string          `yaml:"service_name"`
	Environment           string          `yaml:"environment"`
	OTELEndpoint          string          `yaml:"otel_endpoint"`
	OTELEnabled           *bool           `yaml:"otel_enabled"`
	LogLevel              string          `yaml:"log_level"`
	RequestTimeoutSeconds float64         `yaml:"request_timeout_seconds"`
	ConnectTimeoutSeconds float64         `yaml:"connect_timeout_seconds"`
	TLSVerify             *bool           `yaml:"tls_verify"`
	XSynthetic            *bool           `yaml:"x_synthetic"`
	TokenPoolSize         int             `yaml:"token_pool_size"`
	SeedAdminUser         *bool           `yaml:"seed_admin_user"`
	JSONReportPath        string          `yaml:"json_report_path"`
	Profile               *ProfileConfig  `yaml:"profile"`
	Thresholds            *ThresholdConfig `yaml:"thresholds"`
	Mesh                  *MeshConfig     `yaml:"mesh"`
}

// LoadFile loads configuration from a YAML file, then applies env overrides.
func LoadFile(path string) (*Config, error) {
	cfg := Default()

	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}

	var f yamlFile
	if err := yaml.Unmarshal(data, &f); err != nil {
		return nil, err
	}

	if f.BaseURL != "" {
		cfg.BaseURL = f.BaseURL
	}
	if f.InternalBaseURL != "" {
		cfg.InternalBaseURL = f.InternalBaseURL
	}
	if f.ServiceName != "" {
		cfg.ServiceName = f.ServiceName
	}
	if f.Environment != "" {
		cfg.Environment = f.Environment
	}
	if f.OTELEndpoint != "" {
		cfg.OTELEndpoint = f.OTELEndpoint
	}
	if f.OTELEnabled != nil {
		cfg.OTELEnabled = *f.OTELEnabled
	}
	if f.LogLevel != "" {
		cfg.LogLevel = f.LogLevel
	}
	if f.RequestTimeoutSeconds > 0 {
		cfg.RequestTimeoutSeconds = f.RequestTimeoutSeconds
	}
	if f.ConnectTimeoutSeconds > 0 {
		cfg.ConnectTimeoutSeconds = f.ConnectTimeoutSeconds
	}
	if f.TLSVerify != nil {
		cfg.TLSVerify = *f.TLSVerify
	}
	if f.XSynthetic != nil {
		cfg.XSynthetic = *f.XSynthetic
	}
	if f.TokenPoolSize > 0 {
		cfg.TokenPoolSize = f.TokenPoolSize
	}
	if f.SeedAdminUser != nil {
		cfg.SeedAdminUser = *f.SeedAdminUser
	}
	if f.JSONReportPath != "" {
		cfg.JSONReportPath = f.JSONReportPath
	}
	if f.Profile != nil {
		cfg.Profile = *f.Profile
	}
	if f.Thresholds != nil {
		cfg.Thresholds = *f.Thresholds
	}
	if f.Mesh != nil {
		cfg.Mesh = *f.Mesh
	}

	applyEnv(cfg)
	return cfg, nil
}

// Load returns a Config with defaults and env overrides applied.
func Load(yamlPath string) (*Config, error) {
	if yamlPath != "" {
		return LoadFile(yamlPath)
	}
	cfg := Default()
	applyEnv(cfg)
	return cfg, nil
}

func applyEnv(cfg *Config) {
	if v := os.Getenv("SYNTH_BASE_URL"); v != "" {
		cfg.BaseURL = v
	}
	if v := os.Getenv("SYNTH_INTERNAL_URL"); v != "" {
		cfg.InternalBaseURL = v
	}
	if v := os.Getenv("SYNTH_SERVICE_NAME"); v != "" {
		cfg.ServiceName = v
	}
	if v := os.Getenv("SYNTH_ENVIRONMENT"); v != "" {
		cfg.Environment = v
	}
	if v := os.Getenv("SYNTH_OTEL_ENDPOINT"); v != "" {
		cfg.OTELEndpoint = v
	}
	if v := os.Getenv("OTEL_EXPORTER_OTLP_ENDPOINT"); v != "" {
		cfg.OTELEndpoint = v
	}
	if v := os.Getenv("SYNTH_LOG_LEVEL"); v != "" {
		cfg.LogLevel = strings.ToUpper(v)
	}
	if v := os.Getenv("SYNTH_TLS_VERIFY"); v != "" {
		cfg.TLSVerify = v == "1" || strings.EqualFold(v, "true") || strings.EqualFold(v, "yes")
	}
	if v := os.Getenv("SYNTH_TOKEN_POOL_SIZE"); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			cfg.TokenPoolSize = n
		}
	}
	if v := os.Getenv("SYNTH_JSON_REPORT"); v != "" {
		cfg.JSONReportPath = v
	}
}

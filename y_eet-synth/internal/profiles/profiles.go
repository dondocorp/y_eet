// Package profiles defines named traffic profiles.
package profiles

import (
	"fmt"
	"strings"

	"y_eet-synth/internal/config"
)

// All defines all available traffic profiles by name.
var All = map[string]config.ProfileConfig{
	"smoke": {
		Name:            "smoke",
		Concurrency:     5,
		DurationSeconds: 30,
		RPSTarget:       5.0,
		ScenarioWeights: config.ScenarioWeights{
			"anonymous":    0.20,
			"authenticated": 0.30,
			"active_bettor": 0.30,
			"wallet_heavy": 0.15,
			"admin":        0.05,
		},
	},
	"low": {
		Name:            "low",
		Concurrency:     5,
		DurationSeconds: 120,
		RPSTarget:       10.0,
		ScenarioWeights: config.ScenarioWeights{
			"anonymous":    0.15,
			"authenticated": 0.30,
			"active_bettor": 0.35,
			"wallet_heavy": 0.15,
			"admin":        0.05,
		},
	},
	"normal": {
		Name:            "normal",
		Concurrency:     20,
		DurationSeconds: 300,
		RPSTarget:       50.0,
		ScenarioWeights: config.ScenarioWeights{
			"anonymous":    0.10,
			"authenticated": 0.25,
			"active_bettor": 0.45,
			"wallet_heavy": 0.15,
			"admin":        0.05,
		},
	},
	"burst": {
		Name:                 "burst",
		Concurrency:          80,
		DurationSeconds:      180,
		RPSTarget:            200.0,
		BurstFactor:          4.0,
		BurstDurationSeconds: 15,
		BurstIntervalSeconds: 30,
		ScenarioWeights: config.ScenarioWeights{
			"anonymous":    0.05,
			"authenticated": 0.15,
			"active_bettor": 0.65,
			"wallet_heavy": 0.10,
			"admin":        0.05,
		},
	},
	"chaos": {
		Name:            "chaos",
		Concurrency:     15,
		DurationSeconds: 180,
		RPSTarget:       30.0,
		ChaosEnabled:    true,
		ScenarioWeights: config.ScenarioWeights{
			"anonymous":    0.10,
			"authenticated": 0.25,
			"active_bettor": 0.40,
			"wallet_heavy": 0.20,
			"admin":        0.05,
		},
	},
	"mesh": {
		Name:            "mesh",
		Concurrency:     10,
		DurationSeconds: 120,
		RPSTarget:       20.0,
		MeshValidation:  true,
		ScenarioWeights: config.ScenarioWeights{
			"anonymous":    0.10,
			"authenticated": 0.30,
			"active_bettor": 0.40,
			"wallet_heavy": 0.15,
			"admin":        0.05,
		},
	},
	"flood": {
		Name:                 "flood",
		Concurrency:          300,
		DurationSeconds:      600,
		RPSTarget:            500.0,
		BurstFactor:          5.0,
		BurstDurationSeconds: 30,
		BurstIntervalSeconds: 90,
		ScenarioWeights: config.ScenarioWeights{
			"anonymous":           0.03,
			"authenticated":       0.08,
			"registration_funnel": 0.14,
			"active_bettor":       0.22,
			"live_event_bettor":   0.28,
			"high_roller":         0.12,
			"wallet_heavy":        0.10,
			"admin":               0.03,
		},
	},
	"onboarding": {
		Name:                 "onboarding",
		Concurrency:          150,
		DurationSeconds:      300,
		RPSTarget:            200.0,
		BurstFactor:          2.5,
		BurstDurationSeconds: 20,
		BurstIntervalSeconds: 60,
		ScenarioWeights: config.ScenarioWeights{
			"registration_funnel": 0.55,
			"authenticated":       0.15,
			"active_bettor":       0.18,
			"wallet_heavy":        0.08,
			"anonymous":           0.04,
		},
	},
	"canary": {
		Name:             "canary",
		Concurrency:      10,
		DurationSeconds:  120,
		RPSTarget:        25.0,
		CanaryValidation: true,
		MeshValidation:   true,
		ScenarioWeights: config.ScenarioWeights{
			"anonymous":    0.05,
			"authenticated": 0.30,
			"active_bettor": 0.40,
			"wallet_heavy": 0.20,
			"admin":        0.05,
		},
	},
}

// Get returns a profile by name or an error if not found.
func Get(name string) (config.ProfileConfig, error) {
	p, ok := All[name]
	if !ok {
		names := make([]string, 0, len(All))
		for n := range All {
			names = append(names, n)
		}
		return config.ProfileConfig{}, fmt.Errorf(
			"unknown profile %q; available: %s", name, strings.Join(names, ", "),
		)
	}
	return p, nil
}

// Names returns all available profile names.
func Names() []string {
	out := make([]string, 0, len(All))
	for n := range All {
		out = append(out, n)
	}
	return out
}

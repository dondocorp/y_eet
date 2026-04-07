# y_eet-synth Makefile — Go implementation
# No virtualenv, no pip. Build once, run anywhere.

BINARY     := y_eet-synth
BASE_URL   ?= http://localhost:8080
REPORT     ?= report.json
CANARY_VER ?= canary
CANARY_W   ?= 0.10

.PHONY: build clean smoke run-normal run-burst run-low run-mesh run-canary run-chaos \
        trace retry list-profiles ci-smoke ci-mesh ci-canary help

# ── Build ─────────────────────────────────────────────────────────────────────

build:
	go build -o $(BINARY) .

clean:
	rm -f $(BINARY) report*.json

# ── Traffic runs ──────────────────────────────────────────────────────────────

smoke: build
	./$(BINARY) smoke --base-url $(BASE_URL) --json-report report-smoke.json

run-normal: build
	./$(BINARY) run --profile normal --base-url $(BASE_URL) --json-report report-normal.json

run-low: build
	./$(BINARY) run --profile low --base-url $(BASE_URL) --json-report report-low.json

run-burst: build
	./$(BINARY) run --profile burst --base-url $(BASE_URL) --json-report report-burst.json

run-chaos: build
	@echo "WARNING: Chaos mode — run only against staging!"
	./$(BINARY) chaos --base-url $(BASE_URL) --json-report report-chaos.json

# ── Mesh / Istio validation ───────────────────────────────────────────────────

run-mesh: build
	./$(BINARY) mesh --validate-all --base-url $(BASE_URL) --json-report report-mesh.json

run-canary: build
	./$(BINARY) canary \
	  --expected-version $(CANARY_VER) \
	  --expected-weight  $(CANARY_W) \
	  --base-url         $(BASE_URL) \
	  --json-report      report-canary.json

trace: build
	./$(BINARY) trace --sample-size 200 --base-url $(BASE_URL) --json-report report-trace.json

retry: build
	./$(BINARY) retry --duration 60 --base-url $(BASE_URL) --json-report report-retry.json

list-profiles: build
	./$(BINARY) list-profiles

# ── CI helpers ────────────────────────────────────────────────────────────────
# Exit code is embedded in the binary — report exit code is the binary exit code.

ci-smoke: build
	./$(BINARY) smoke --base-url $(BASE_URL) --json-report report-smoke.json

ci-mesh: build
	./$(BINARY) mesh --validate-all --base-url $(BASE_URL) --json-report report-mesh.json

ci-canary: build
	./$(BINARY) canary \
	  --expected-version $(CANARY_VER) \
	  --expected-weight  $(CANARY_W) \
	  --base-url $(BASE_URL) \
	  --json-report report-canary.json

# ── Help ──────────────────────────────────────────────────────────────────────

help:
	@echo ""
	@echo "  make build             Compile the Go binary"
	@echo "  make smoke             30s smoke test"
	@echo "  make run-normal        5min normal production profile"
	@echo "  make run-burst         3min burst/spike profile"
	@echo "  make run-chaos         3min chaos profile  (STAGING ONLY)"
	@echo "  make run-mesh          2min Istio mesh validation"
	@echo "  make run-canary        Canary split validation (CANARY_VER, CANARY_W)"
	@echo "  make trace             Trace propagation check"
	@echo "  make retry             Retry/timeout verification"
	@echo "  make ci-smoke          Smoke test — exits non-zero on failures"
	@echo "  make ci-mesh           Mesh validation — exits non-zero on failures"
	@echo "  make ci-canary         Canary validation — exits non-zero on failures"
	@echo "  make clean             Remove binary and report files"
	@echo ""
	@echo "  BASE_URL=$(BASE_URL)"
	@echo "  CANARY_VER=$(CANARY_VER)  CANARY_W=$(CANARY_W)"
	@echo ""

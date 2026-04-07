.PHONY: install smoke run-normal run-burst run-chaos run-mesh run-canary trace retry clean help

PYTHON      ?= python3
VENV        := .venv
PIP         := $(VENV)/bin/pip
SYNTH       := $(VENV)/bin/python main.py
BASE_URL    ?= http://localhost:8080

# ── Setup ─────────────────────────────────────────────────────────────────────

install:
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	@echo "✓ virtualenv ready at $(VENV)"

# ── Traffic runs ──────────────────────────────────────────────────────────────

smoke:
	$(SYNTH) smoke --base-url $(BASE_URL) --json-report report-smoke.json

run-normal:
	$(SYNTH) run --profile normal --duration 300 --base-url $(BASE_URL) \
	             --json-report report-normal.json

run-low:
	$(SYNTH) run --profile low --duration 600 --base-url $(BASE_URL) \
	             --json-report report-low.json

run-burst:
	$(SYNTH) run --profile burst --duration 180 --base-url $(BASE_URL) \
	             --json-report report-burst.json

run-chaos:
	@echo "WARNING: Chaos mode — run only against staging!"
	$(SYNTH) chaos --duration 180 --base-url $(BASE_URL) \
	               --json-report report-chaos.json

# ── Mesh / Istio validation ────────────────────────────────────────────────────

run-mesh:
	$(SYNTH) mesh --validate-all --duration 120 --base-url $(BASE_URL) \
	              --json-report report-mesh.json

run-canary:
	$(SYNTH) canary \
	  --expected-version $(CANARY_VERSION) \
	  --expected-weight  $(CANARY_WEIGHT) \
	  --base-url         $(BASE_URL) \
	  --json-report      report-canary.json

trace:
	$(SYNTH) trace --sample-size 200 --base-url $(BASE_URL) \
	               --json-report report-trace.json

retry:
	$(SYNTH) retry --duration 60 --base-url $(BASE_URL) \
	               --json-report report-retry.json

# ── CI helpers ────────────────────────────────────────────────────────────────

# Used in GitLab CI post-deploy stage — exits non-zero on failures
ci-smoke: smoke
	@cat report-smoke.json | python -c \
	  "import json,sys; r=json.load(sys.stdin); sys.exit(r['evaluation']['exit_code'])"

ci-mesh: run-mesh
	@cat report-mesh.json | python -c \
	  "import json,sys; r=json.load(sys.stdin); sys.exit(r['evaluation']['exit_code'])"

ci-canary: run-canary
	@cat report-canary.json | python -c \
	  "import json,sys; r=json.load(sys.stdin); sys.exit(r['evaluation']['exit_code'])"

# ── Utility ───────────────────────────────────────────────────────────────────

list-profiles:
	$(SYNTH) list-profiles

clean:
	rm -f report*.json

help:
	@echo ""
	@echo "  make install           Install dependencies into .venv"
	@echo "  make smoke             30s smoke test"
	@echo "  make run-normal        5min normal production profile"
	@echo "  make run-burst         3min burst/spike profile"
	@echo "  make run-chaos         3min chaos profile  (STAGING ONLY)"
	@echo "  make run-mesh          2min Istio mesh validation"
	@echo "  make run-canary        Canary split validation (set CANARY_VERSION, CANARY_WEIGHT)"
	@echo "  make trace             Trace propagation check"
	@echo "  make retry             Retry/timeout verification"
	@echo "  make ci-smoke          Smoke test + CI exit code"
	@echo "  make ci-mesh           Mesh validation + CI exit code"
	@echo "  make ci-canary         Canary validation + CI exit code"
	@echo "  make clean             Remove report files"
	@echo ""
	@echo "  BASE_URL=$(BASE_URL)"

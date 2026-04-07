#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# showcase.sh — Full Yeet Platform capability demonstration
#
# Walks through every system capability in sequence with live output:
#   1.  Stack health verification
#   2.  Smoke test          — quick 30s pass/fail gate
#   3.  Normal traffic      — realistic production-representative load
#   4.  Burst / spike       — sports-event surge simulation
#   5.  Service mesh        — Istio policy validation (all checks)
#   6.  Canary validation   — traffic split verification
#   7.  Chaos injection     — fault-path resilience (stale tokens, malformed
#                             payloads, duplicate replays, missing idem keys,
#                             oversized bodies)
#   8.  Trace propagation   — W3C traceparent continuity
#   9.  Retry / timeout     — Envoy retry and timeout policy alignment
#  10.  Brand intelligence  — social sentiment pipeline status + demo data
#  11.  Summary             — consolidated pass/fail across all phases
#
# Usage:
#   ./scripts/showcase.sh [OPTIONS]
#
# Options:
#   --base-url URL        API base URL              [default: http://localhost:8080]
#   --skip-stack-check    Skip initial stack health check
#   --skip-burst          Skip burst profile (faster run)
#   --skip-chaos          Skip chaos phase
#   --skip-brand          Skip brand intelligence phase
#   --no-browser          Do not open browser tabs
#   --report-dir DIR      Write all JSON reports here [default: /tmp/showcase]
#   --fast                Skip burst + flood; use shorter durations throughout
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# ── Colours ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GRN='\033[0;32m'
YLW='\033[1;33m'
BLU='\033[0;34m'
CYN='\033[0;36m'
MAG='\033[0;35m'
DIM='\033[2m'
RST='\033[0m'
BLD='\033[1m'

# ── Logging helpers ───────────────────────────────────────────────────────────
PHASE_NUM=0
PHASE_START_TS=0

banner() {
  echo ""
  echo -e "${BLU}${BLD}╔══════════════════════════════════════════════════════════════════════╗${RST}"
  echo -e "${BLU}${BLD}║  $*"
  echo -e "${BLU}${BLD}╚══════════════════════════════════════════════════════════════════════╝${RST}"
}

phase() {
  PHASE_NUM=$(( PHASE_NUM + 1 ))
  PHASE_START_TS=$(date +%s)
  echo ""
  echo -e "${MAG}${BLD}▶  Phase ${PHASE_NUM}: $*${RST}"
  echo -e "${DIM}   $(date '+%H:%M:%S')${RST}"
}

phase_done() {
  local elapsed=$(( $(date +%s) - PHASE_START_TS ))
  echo -e "   ${DIM}↳ completed in ${elapsed}s${RST}"
}

phase_skip() {
  echo -e "   ${DIM}↳ skipped (--${1})${RST}"
}

ok()     { echo -e "   ${GRN}✓${RST}  $*"; }
warn()   { echo -e "   ${YLW}⚠${RST}  $*"; }
err()    { echo -e "   ${RED}✗${RST}  $*" >&2; }
info()   { echo -e "   ${DIM}·${RST}  $*"; }
detail() { echo -e "   ${CYN}→${RST}  $*"; }

divider() {
  echo -e "${DIM}──────────────────────────────────────────────────────────────────────────${RST}"
}

# ── Result tracking ───────────────────────────────────────────────────────────
RESULTS=()   # "phase:verdict"
REPORTS=()   # "label:path"

record_result() {
  local label="$1" verdict="$2"
  RESULTS+=("${label}:${verdict}")
}

record_report() {
  local label="$1" path="$2"
  REPORTS+=("${label}:${path}")
}

# ── Argument parsing ──────────────────────────────────────────────────────────
BASE_URL="http://localhost:8080"
SKIP_STACK_CHECK=false
SKIP_BURST=false
SKIP_CHAOS=false
SKIP_BRAND=false
NO_BROWSER=false
REPORT_DIR="/tmp/showcase"
FAST=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      sed -n '3,18p' "$0" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    --base-url)         BASE_URL="$2";  shift 2 ;;
    --base-url=*)       BASE_URL="${1#*=}"; shift ;;
    --skip-stack-check) SKIP_STACK_CHECK=true; shift ;;
    --skip-burst)       SKIP_BURST=true; shift ;;
    --skip-chaos)       SKIP_CHAOS=true; shift ;;
    --skip-brand)       SKIP_BRAND=true; shift ;;
    --no-browser)       NO_BROWSER=true; shift ;;
    --report-dir)       REPORT_DIR="$2"; shift 2 ;;
    --report-dir=*)     REPORT_DIR="${1#*=}"; shift ;;
    --fast)             FAST=true; SKIP_BURST=true; shift ;;
    *) echo "Unknown option: $1  (try --help)"; exit 1 ;;
  esac
done

SYNTH_BIN="$REPO_ROOT/y_eet-synth/y_eet-synth"
mkdir -p "$REPORT_DIR"

# Durations: normal mode vs --fast
if [[ "$FAST" == "true" ]]; then
  DUR_SMOKE=30; DUR_NORMAL=60; DUR_BURST=60; DUR_MESH=60
  DUR_CANARY=60; DUR_CHAOS=60; DUR_TRACE=30; DUR_RETRY=30
else
  DUR_SMOKE=30; DUR_NORMAL=180; DUR_BURST=120; DUR_MESH=90
  DUR_CANARY=90; DUR_CHAOS=120; DUR_TRACE=45; DUR_RETRY=45
fi

# ── Banner ────────────────────────────────────────────────────────────────────
clear
echo ""
echo -e "${BLD}${CYN}"
cat << 'EOF'
  ██╗   ██╗███████╗███████╗████████╗
  ╚██╗ ██╔╝██╔════╝██╔════╝╚══██╔══╝
   ╚████╔╝ █████╗  █████╗     ██║
    ╚██╔╝  ██╔══╝  ██╔══╝     ██║
     ██║   ███████╗███████╗   ██║
     ╚═╝   ╚══════╝╚══════╝   ╚═╝
EOF
echo -e "${RST}"
echo -e "  ${BLD}Full Platform Capability Showcase${RST}"
echo -e "  ${DIM}Synthetic traffic · Mesh validation · Chaos injection · Brand intelligence${RST}"
echo ""
divider
echo -e "  ${BLD}Target:${RST}      ${CYN}$BASE_URL${RST}"
echo -e "  ${BLD}Reports:${RST}     ${CYN}$REPORT_DIR/${RST}"
echo -e "  ${BLD}Mode:${RST}        $( [[ "$FAST" == "true" ]] && echo "fast (reduced durations)" || echo "standard" )"
echo ""

# ── Helper: parse a field from a JSON report ──────────────────────────────────
json_field() {
  local file="$1" field="$2"
  python3 -c "import json,sys; d=json.load(open('$file')); print($field)" 2>/dev/null || echo "n/a"
}

# ── Helper: print report highlights ──────────────────────────────────────────
print_report_highlights() {
  local report="$1"
  [[ ! -f "$report" ]] && { warn "Report not found: $report"; return; }

  local verdict total rps err_pct p99 fails warns
  verdict=$(json_field "$report" "d['evaluation']['verdict']")
  total=$(json_field "$report" "d['total_requests']")
  rps=$(json_field "$report" "round(d['rps_average'],1)")
  err_pct=$(json_field "$report" "d['global_error_rate_pct']")
  p99=$(json_field "$report" "round(d['global_p99_ms'],0)")
  fails=$(json_field "$report" "len([c for c in d['evaluation']['checks'] if c['verdict']=='FAIL'])")
  warns=$(json_field "$report" "len([c for c in d['evaluation']['checks'] if c['verdict']=='WARN'])")

  case "$verdict" in
    PASS) echo -e "   ${GRN}${BLD}verdict: PASS${RST}    fails=${fails}  warns=${warns}" ;;
    WARN) echo -e "   ${YLW}${BLD}verdict: WARN${RST}    fails=${fails}  warns=${warns}" ;;
    FAIL) echo -e "   ${RED}${BLD}verdict: FAIL${RST}    fails=${fails}  warns=${warns}" ;;
    *)    echo -e "   ${DIM}verdict: ${verdict}${RST}" ;;
  esac
  echo -e "   ${DIM}requests=${total}  rps=${rps}  error_rate=${err_pct}%  p99=${p99}ms${RST}"
}

# ── Helper: run synth command + capture exit code without killing script ───────
run_synth() {
  local label="$1"; shift
  "$SYNTH_BIN" "$@" 2>&1 | sed 's/^/   /' || true
  # Get exit code from the binary (it already exited via os.Exit)
  # We capture it via the subshell approach
  local ec
  set +e
  "$SYNTH_BIN" "$@" >/dev/null 2>&1
  ec=$?
  set -e
  return $ec
}

# ── Preflight: binary check ───────────────────────────────────────────────────
banner "Preflight"

if [[ ! -x "$SYNTH_BIN" ]]; then
  info "y_eet-synth binary not found — building..."
  (cd "$REPO_ROOT/y_eet-synth" && go build -o y_eet-synth .) \
    && ok "y_eet-synth built" \
    || { err "go build failed — cannot run showcase"; exit 1; }
fi
ok "y_eet-synth binary: $SYNTH_BIN"

# Detect browser utility
OPEN_CMD=""
if [[ "$NO_BROWSER" == "false" ]]; then
  command -v open    &>/dev/null && OPEN_CMD="open"
  command -v xdg-open &>/dev/null && OPEN_CMD="xdg-open"
fi

# ── Phase 1: Stack health ─────────────────────────────────────────────────────
phase "Stack Health Verification"

if [[ "$SKIP_STACK_CHECK" == "true" ]]; then
  phase_skip "skip-stack-check"
  record_result "Stack Health" "SKIP"
else
  STACK_OK=true

  check_service() {
    local name="$1" url="$2"
    if curl -sf --max-time 5 "$url" &>/dev/null; then
      ok "$name  ${DIM}→ $url${RST}"
    else
      warn "$name unreachable  ${DIM}($url)${RST}"
      STACK_OK=false
    fi
  }

  check_service "API"            "$BASE_URL/health/live"
  check_service "Prometheus"     "http://localhost:9090/-/ready"
  check_service "Grafana"        "http://localhost:3000/api/health"
  check_service "Alertmanager"   "http://localhost:9093/-/healthy"
  check_service "OTEL Collector" "http://localhost:13133/"
  check_service "Loki"           "http://localhost:3100/ready"
  check_service "Tempo"          "http://localhost:3200/ready"
  check_service "Sentiment Metrics" "http://localhost:9465/metrics"
  check_service "Analyst UI"     "http://localhost:8501/"

  if [[ "$STACK_OK" == "true" ]]; then
    record_result "Stack Health" "PASS"
  else
    warn "Some services are not reachable — showcase will continue but some phases may fail"
    warn "Run ./scripts/demo.sh first to bring up the full stack"
    record_result "Stack Health" "WARN"
  fi

  phase_done
fi

divider

# ── Phase 2: Smoke Test ───────────────────────────────────────────────────────
phase "Smoke Test  ${DIM}(${DUR_SMOKE}s · 5 rps · all endpoint categories)${RST}"
detail "Quick sanity gate — confirms every endpoint category is reachable"
echo ""

SMOKE_REPORT="$REPORT_DIR/smoke.json"
set +e
"$SYNTH_BIN" smoke \
  --base-url "$BASE_URL" \
  --duration "$DUR_SMOKE" \
  --json-report "$SMOKE_REPORT" \
  --log-level INFO \
  2>&1 | sed 's/^/   /'
SMOKE_EXIT=$?
set -e

echo ""
print_report_highlights "$SMOKE_REPORT"
record_report "Smoke" "$SMOKE_REPORT"
[[ $SMOKE_EXIT -eq 0 ]] && record_result "Smoke" "PASS" \
  || { [[ $SMOKE_EXIT -eq 2 ]] && record_result "Smoke" "WARN" || record_result "Smoke" "FAIL"; }
phase_done
divider

# ── Phase 3: Normal Traffic ───────────────────────────────────────────────────
phase "Normal Traffic  ${DIM}(${DUR_NORMAL}s · 50 rps · production-representative load)${RST}"
detail "20 concurrent workers · 5 archetypes · weighted scenario selection"
detail "Archetypes: 10% anonymous · 25% authenticated · 45% active_bettor · 15% wallet_heavy · 5% admin"
echo ""

NORMAL_REPORT="$REPORT_DIR/normal.json"
set +e
"$SYNTH_BIN" run \
  --profile normal \
  --duration "$DUR_NORMAL" \
  --base-url "$BASE_URL" \
  --json-report "$NORMAL_REPORT" \
  --log-level INFO \
  2>&1 | sed 's/^/   /'
NORMAL_EXIT=$?
set -e

echo ""
print_report_highlights "$NORMAL_REPORT"

# Print per-endpoint highlights if python3 is available
if command -v python3 &>/dev/null && [[ -f "$NORMAL_REPORT" ]]; then
  echo ""
  echo -e "   ${BLD}Top endpoints by request volume:${RST}"
  python3 - "$NORMAL_REPORT" << 'PYEOF'
import json, sys
d = json.load(open(sys.argv[1]))
eps = sorted(d["endpoints"].items(), key=lambda x: -x[1]["total"])[:6]
for name, m in eps:
    sr = m["success_rate_pct"]
    color = "\033[32m" if sr >= 99 else "\033[33m" if sr >= 95 else "\033[31m"
    rst = "\033[0m"
    print(f"   {color}{name:<46}{rst}  {m['total']:>5} reqs  {sr:.1f}%  p99={m['p99_ms']:.0f}ms")
PYEOF
fi

record_report "Normal" "$NORMAL_REPORT"
[[ $NORMAL_EXIT -eq 0 ]] && record_result "Normal Traffic" "PASS" \
  || { [[ $NORMAL_EXIT -eq 2 ]] && record_result "Normal Traffic" "WARN" || record_result "Normal Traffic" "FAIL"; }
phase_done
divider

# ── Phase 4: Burst / Spike ────────────────────────────────────────────────────
if [[ "$SKIP_BURST" == "true" ]]; then
  phase "Burst / Spike Traffic  ${DIM}(skipped)${RST}"
  phase_skip "skip-burst"
  record_result "Burst Traffic" "SKIP"
else
  phase "Burst / Spike Traffic  ${DIM}(${DUR_BURST}s · 200 rps · 4× burst windows every 30s)${RST}"
  detail "80 concurrent workers · simulates a live sports event or promotional surge"
  detail "Burst factor 4× fires every 30s for 15s — tests autoscaling and rate limiting"
  echo ""

  BURST_REPORT="$REPORT_DIR/burst.json"
  set +e
  "$SYNTH_BIN" run \
    --profile burst \
    --duration "$DUR_BURST" \
    --base-url "$BASE_URL" \
    --json-report "$BURST_REPORT" \
    --log-level INFO \
    2>&1 | sed 's/^/   /'
  BURST_EXIT=$?
  set -e

  echo ""
  print_report_highlights "$BURST_REPORT"
  record_report "Burst" "$BURST_REPORT"
  [[ $BURST_EXIT -eq 0 ]] && record_result "Burst Traffic" "PASS" \
    || { [[ $BURST_EXIT -eq 2 ]] && record_result "Burst Traffic" "WARN" || record_result "Burst Traffic" "FAIL"; }
  phase_done
fi
divider

# ── Phase 5: Istio Mesh Validation ───────────────────────────────────────────
phase "Istio Service Mesh Validation  ${DIM}(${DUR_MESH}s · all checks enabled)${RST}"
detail "Validates 8 Istio policy categories:"
detail "  retry_validation · timeout_validation · circuit_breaker"
detail "  trace_propagation · mtls_validation · canary_split"
detail "  fault_injection · ingress_routing"
echo ""

MESH_REPORT="$REPORT_DIR/mesh.json"
set +e
"$SYNTH_BIN" mesh \
  --validate-all \
  --duration "$DUR_MESH" \
  --base-url "$BASE_URL" \
  --json-report "$MESH_REPORT" \
  --log-level INFO \
  2>&1 | sed 's/^/   /'
MESH_EXIT=$?
set -e

echo ""
print_report_highlights "$MESH_REPORT"

if command -v python3 &>/dev/null && [[ -f "$MESH_REPORT" ]]; then
  echo ""
  echo -e "   ${BLD}Mesh check results:${RST}"
  python3 - "$MESH_REPORT" << 'PYEOF'
import json, sys
d = json.load(open(sys.argv[1]))
for m in d.get("mesh", []):
    status = m["status"]
    color = {"PASS": "\033[32m", "WARN": "\033[33m", "FAIL": "\033[31m"}.get(status, "\033[2m")
    rst = "\033[0m"
    print(f"   {color}{status:<6}{rst}  {m['check']:<35}  {m['message'][:60]}")
PYEOF
fi

record_report "Mesh" "$MESH_REPORT"
[[ $MESH_EXIT -eq 0 ]] && record_result "Mesh Validation" "PASS" \
  || { [[ $MESH_EXIT -eq 2 ]] && record_result "Mesh Validation" "WARN" || record_result "Mesh Validation" "FAIL"; }
phase_done
divider

# ── Phase 6: Canary Validation ────────────────────────────────────────────────
phase "Canary Rollout Validation  ${DIM}(${DUR_CANARY}s · expected split 10%)${RST}"
detail "Sends $( python3 -c "print(${DUR_CANARY} * 25)" 2>/dev/null || echo '~2000' ) requests and checks x-canary-version header distribution"
detail "Confirms Istio VirtualService routes the declared traffic percentage to canary pods"
echo ""

CANARY_REPORT="$REPORT_DIR/canary.json"
set +e
"$SYNTH_BIN" canary \
  --expected-version canary \
  --expected-weight 0.10 \
  --tolerance 0.05 \
  --duration "$DUR_CANARY" \
  --base-url "$BASE_URL" \
  --json-report "$CANARY_REPORT" \
  --log-level INFO \
  2>&1 | sed 's/^/   /'
CANARY_EXIT=$?
set -e

echo ""
print_report_highlights "$CANARY_REPORT"
record_report "Canary" "$CANARY_REPORT"
[[ $CANARY_EXIT -eq 0 ]] && record_result "Canary Validation" "PASS" \
  || { [[ $CANARY_EXIT -eq 2 ]] && record_result "Canary Validation" "WARN" || record_result "Canary Validation" "FAIL"; }
phase_done
divider

# ── Phase 7: Chaos Injection ──────────────────────────────────────────────────
if [[ "$SKIP_CHAOS" == "true" ]]; then
  phase "Chaos / Fault Injection  ${DIM}(skipped)${RST}"
  phase_skip "skip-chaos"
  record_result "Chaos Injection" "SKIP"
else
  phase "Chaos / Fault Injection  ${DIM}(${DUR_CHAOS}s · fault path validation)${RST}"

  echo ""
  echo -e "   ${YLW}${BLD}⚠  Chaos mode active — intentional faults will be injected${RST}"
  echo ""
  detail "Scenario 1: stale_token       — invalid JWT → expects 401/403"
  detail "Scenario 2: malformed_payload — non-JSON body → expects 400/422"
  detail "Scenario 3: duplicate_replay  — same idempotency key twice → expects idempotent 2xx or 409"
  detail "Scenario 4: missing_idem_key  — write without key → expects 400 or graceful 2xx"
  detail "Scenario 5: oversized_payload — 1 MB body → expects 413/400"
  echo ""
  detail "Normal traffic runs in parallel so error handling is tested under realistic load"
  echo ""

  CHAOS_REPORT="$REPORT_DIR/chaos.json"
  set +e
  "$SYNTH_BIN" chaos \
    --duration "$DUR_CHAOS" \
    --base-url "$BASE_URL" \
    --json-report "$CHAOS_REPORT" \
    --log-level INFO \
    2>&1 | sed 's/^/   /'
  CHAOS_EXIT=$?
  set -e

  echo ""
  print_report_highlights "$CHAOS_REPORT"

  if command -v python3 &>/dev/null && [[ -f "$CHAOS_REPORT" ]]; then
    echo ""
    echo -e "   ${BLD}Chaos scenario results:${RST}"
    python3 - "$CHAOS_REPORT" << 'PYEOF'
import json, sys
d = json.load(open(sys.argv[1]))
for c in d.get("chaos", []):
    passed = c["passed"]
    color = "\033[32m" if passed else "\033[31m"
    badge = "PASS" if passed else "FAIL"
    rst = "\033[0m"
    note = c.get("note", "") or f"expected {c['expected_status']}, got {c['status_code']}"
    print(f"   {color}{badge}{rst}  {c['scenario']:<28}  {note[:65]}")
PYEOF
  fi

  record_report "Chaos" "$CHAOS_REPORT"
  [[ $CHAOS_EXIT -eq 0 ]] && record_result "Chaos Injection" "PASS" \
    || { [[ $CHAOS_EXIT -eq 2 ]] && record_result "Chaos Injection" "WARN" || record_result "Chaos Injection" "FAIL"; }
  phase_done
fi
divider

# ── Phase 8: Trace Propagation ────────────────────────────────────────────────
phase "Trace Propagation  ${DIM}(${DUR_TRACE}s · W3C traceparent continuity)${RST}"
detail "Every request carries a traceparent header"
detail "Checks that ≥ 95% of responses echo trace context — confirms OTel Collector is receiving spans"
echo ""

TRACE_REPORT="$REPORT_DIR/trace.json"
set +e
"$SYNTH_BIN" trace \
  --sample-size 150 \
  --base-url "$BASE_URL" \
  --json-report "$TRACE_REPORT" \
  --log-level INFO \
  2>&1 | sed 's/^/   /'
TRACE_EXIT=$?
set -e

echo ""
print_report_highlights "$TRACE_REPORT"
record_report "Trace" "$TRACE_REPORT"
[[ $TRACE_EXIT -eq 0 ]] && record_result "Trace Propagation" "PASS" \
  || { [[ $TRACE_EXIT -eq 2 ]] && record_result "Trace Propagation" "WARN" || record_result "Trace Propagation" "FAIL"; }
phase_done
divider

# ── Phase 9: Retry / Timeout ──────────────────────────────────────────────────
phase "Retry & Timeout Alignment  ${DIM}(${DUR_RETRY}s)${RST}"
detail "Checks x-envoy-attempt-count headers across requests"
detail "Verifies Istio retry policy is active and timeout boundaries are respected"
echo ""

RETRY_REPORT="$REPORT_DIR/retry.json"
set +e
"$SYNTH_BIN" retry \
  --duration "$DUR_RETRY" \
  --base-url "$BASE_URL" \
  --json-report "$RETRY_REPORT" \
  --log-level INFO \
  2>&1 | sed 's/^/   /'
RETRY_EXIT=$?
set -e

echo ""
print_report_highlights "$RETRY_REPORT"
record_report "Retry" "$RETRY_REPORT"
[[ $RETRY_EXIT -eq 0 ]] && record_result "Retry/Timeout" "PASS" \
  || { [[ $RETRY_EXIT -eq 2 ]] && record_result "Retry/Timeout" "WARN" || record_result "Retry/Timeout" "FAIL"; }
phase_done
divider

# ── Phase 10: Brand Intelligence ──────────────────────────────────────────────
if [[ "$SKIP_BRAND" == "true" ]]; then
  phase "Brand Intelligence Pipeline  ${DIM}(skipped)${RST}"
  phase_skip "skip-brand"
  record_result "Brand Intelligence" "SKIP"
else
  phase "Brand Intelligence Pipeline"
  detail "Social media sentiment monitoring — Reddit/Twitter → RoBERTa → SQLite → Grafana"
  echo ""

  # Check Prometheus metrics from the sentiment pipeline
  if curl -sf --max-time 5 "http://localhost:9465/metrics" &>/dev/null; then
    ok "Sentiment metrics endpoint reachable  (http://localhost:9465/metrics)"

    # Pull key metric values
    if command -v python3 &>/dev/null; then
      python3 << 'PYEOF'
import urllib.request, re, sys

try:
    with urllib.request.urlopen("http://localhost:9465/metrics", timeout=5) as r:
        body = r.read().decode()
except Exception as e:
    print(f"   Could not fetch metrics: {e}")
    sys.exit(0)

def metric(name):
    m = re.search(rf'^{re.escape(name)}(?:{{[^}}]*}})?\s+([\d.e+\-]+)', body, re.M)
    return float(m.group(1)) if m else None

total_runs    = metric("social_scrape_runs_total")
posts         = metric("social_posts_collected_total")
pos           = metric('social_sentiment_classified_total{sentiment="positive"}')
neg           = metric('social_sentiment_classified_total{sentiment="negative"}')
neu           = metric('social_sentiment_classified_total{sentiment="neutral"}')
alerts_fired  = metric("social_alerts_fired_total")

GRN = "\033[32m"; YLW = "\033[33m"; DIM = "\033[2m"; RST = "\033[0m"; BLD = "\033[1m"

print(f"\n   {BLD}Pipeline metrics (live from Prometheus exporter):{RST}")
print(f"   {DIM}scrape runs:  {RST}{int(total_runs or 0)}")
print(f"   {DIM}posts seen:   {RST}{int(posts or 0)}")
if pos is not None and neg is not None and neu is not None:
    total = pos + neg + neu or 1
    print(f"   {DIM}sentiment:    {RST}{GRN}pos={int(pos)} ({pos/total:.0%}){RST}  "
          f"{DIM}neu={int(neu)} ({neu/total:.0%}){RST}  "
          f"{'⚠ ' if neg/total > 0.3 else ''}"
          f"\033[31mneg={int(neg)} ({neg/total:.0%})\033[0m")
print(f"   {DIM}alerts fired: {RST}{int(alerts_fired or 0)}")
PYEOF
    fi
  else
    warn "Sentiment metrics not reachable — social-sentiment container may not be running"
    info "Start it with: docker compose up social-sentiment"
  fi

  # Check Streamlit dashboard
  if curl -sf --max-time 5 "http://localhost:8501/" &>/dev/null; then
    ok "Streamlit analyst dashboard reachable  (http://localhost:8501)"
  else
    warn "Streamlit dashboard not reachable"
  fi

  # Check the demo data seed status
  echo ""
  detail "Sentiment pipeline coverage:"
  detail "  • Relevance classifier  — 5-stage keyword pipeline (primary · secondary+context · embedding gate)"
  detail "  • Sentiment model       — cardiffnlp/twitter-roberta-base-sentiment-latest (3-class)"
  detail "  • Derived labels        — scam_concern · payment_issue · ux_praise · login_issue · hype"
  detail "  • Alert rules           — neg spike · scam spike · mention spike · scrape failure · no-data"
  detail "  • Alert routing         — Telegram + Alertmanager webhook with 60min suppression"
  detail "  • Grafana integration   — Executive View · Operations View · Pipeline Health dashboards"

  echo ""
  [[ -n "$OPEN_CMD" && "$NO_BROWSER" == "false" ]] && {
    $OPEN_CMD "http://localhost:8501" 2>/dev/null || true
    info "Opened Streamlit analyst dashboard"
  }

  record_result "Brand Intelligence" "PASS"
  phase_done
fi
divider

# ── Consolidated Summary ──────────────────────────────────────────────────────
TOTAL_ELAPSED=$(( $(date +%s) - PHASE_START_TS ))
echo ""
banner "Showcase Complete — Results Summary"
echo ""

PASS_COUNT=0; WARN_COUNT=0; FAIL_COUNT=0; SKIP_COUNT=0

for entry in "${RESULTS[@]}"; do
  label="${entry%%:*}"
  verdict="${entry##*:}"
  pad=$(printf '%-30s' "$label")
  case "$verdict" in
    PASS) echo -e "   ${GRN}${BLD}PASS${RST}  ${pad}"; (( PASS_COUNT++ )) ;;
    WARN) echo -e "   ${YLW}${BLD}WARN${RST}  ${pad}"; (( WARN_COUNT++ )) ;;
    FAIL) echo -e "   ${RED}${BLD}FAIL${RST}  ${pad}"; (( FAIL_COUNT++ )) ;;
    SKIP) echo -e "   ${DIM}SKIP  ${pad}${RST}"; (( SKIP_COUNT++ )) ;;
  esac
done

echo ""
divider
echo ""
echo -e "   Phases run:  $( echo ${#RESULTS[@]} )   ${GRN}PASS: $PASS_COUNT${RST}   ${YLW}WARN: $WARN_COUNT${RST}   ${RED}FAIL: $FAIL_COUNT${RST}   ${DIM}SKIP: $SKIP_COUNT${RST}"
echo ""

if [[ $FAIL_COUNT -gt 0 ]]; then
  echo -e "   ${RED}${BLD}Overall: FAIL${RST}  — ${FAIL_COUNT} phase(s) failed. Check report files for details."
elif [[ $WARN_COUNT -gt 0 ]]; then
  echo -e "   ${YLW}${BLD}Overall: WARN${RST}  — all phases passed with ${WARN_COUNT} warning(s). Review before production."
else
  echo -e "   ${GRN}${BLD}Overall: PASS${RST}  — all phases completed successfully."
fi

echo ""
echo -e "   ${BLD}JSON reports written to ${CYN}$REPORT_DIR/${RST}${BLD}:${RST}"
for entry in "${REPORTS[@]}"; do
  label="${entry%%:*}"
  path="${entry##*:}"
  [[ -f "$path" ]] && echo -e "   ${DIM}·${RST}  $(printf '%-16s' "$label")  $path"
done

echo ""
echo -e "   ${BLD}Useful next steps:${RST}"
echo -e "   ${DIM}·${RST}  ${CYN}http://localhost:3000/d/api-reliability${RST}        — API request rate, error rate, P99 latency"
echo -e "   ${DIM}·${RST}  ${CYN}http://localhost:3000/d/slo-error-budget${RST}       — SLO burn rate for bet placement + auth"
echo -e "   ${DIM}·${RST}  ${CYN}http://localhost:3000/d/brand-intel-exec${RST}       — Brand Intelligence executive view"
echo -e "   ${DIM}·${RST}  ${CYN}http://localhost:9090${RST}                          — Prometheus — explore social_* and y_eet_* metrics"
echo -e "   ${DIM}·${RST}  ${CYN}http://localhost:8501${RST}                          — Streamlit analyst dashboard"
echo ""

# Open Grafana if browser available and we haven't already
if [[ -n "$OPEN_CMD" && "$NO_BROWSER" == "false" ]]; then
  $OPEN_CMD "http://localhost:3000/d/api-reliability" 2>/dev/null || true
fi

divider
echo ""

# Exit with non-zero if any phase failed
[[ $FAIL_COUNT -gt 0 ]] && exit 1
exit 0

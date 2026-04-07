#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# demo.sh — One-command Yeet Platform local demo launcher
#
# Starts the full stack:
#   • PostgreSQL + Redis
#   • Yeet Platform API (Node / Fastify / TypeScript)
#   • OpenTelemetry Collector → Prometheus → Grafana + Loki + Tempo
#   • Alertmanager + Blackbox Exporter
#   • Social Sentiment pipeline + Streamlit analyst dashboard
#   • y_eet-synth synthetic traffic generator
#
# Usage:
#   ./scripts/demo.sh [--skip-synth] [--skip-browser] [--rebuild]
#
# Options:
#   --skip-synth    Start stack without synthetic traffic
#   --skip-browser  Don't open browser tabs automatically
#   --rebuild       Force rebuild of Docker images before starting
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# ── Terminal colours ──────────────────────────────────────────────────────────
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
PHASE_START_TS=0

phase() {
  PHASE_START_TS=$(date +%s)
  echo ""
  echo -e "${BLU}${BLD}━━━  $*${RST}"
}

ok()   { echo -e "  ${GRN}✓${RST}  $*"; }
warn() { echo -e "  ${YLW}⚠${RST}  $*"; }
err()  { echo -e "  ${RED}✗${RST}  $*" >&2; }
info() { echo -e "  ${DIM}·${RST}  $*"; }

phase_done() {
  local elapsed=$(( $(date +%s) - PHASE_START_TS ))
  echo -e "  ${DIM}done in ${elapsed}s${RST}"
}

divider() {
  echo -e "${DIM}─────────────────────────────────────────────────────────────────────────────${RST}"
}

# ── Banner ────────────────────────────────────────────────────────────────────
clear
echo ""
echo -e "${BLD}${CYN}"
echo "  ██╗   ██╗███████╗███████╗████████╗"
echo "  ╚██╗ ██╔╝██╔════╝██╔════╝╚══██╔══╝"
echo "   ╚████╔╝ █████╗  █████╗     ██║   "
echo "    ╚██╔╝  ██╔══╝  ██╔══╝     ██║   "
echo "     ██║   ███████╗███████╗   ██║   "
echo "     ╚═╝   ╚══════╝╚══════╝   ╚═╝   "
echo -e "${RST}"
echo -e "  ${BLD}Crypto-Casino Platform  ·  Local Demo${RST}"
echo -e "  ${DIM}Full observability stack · Social sentiment · Synthetic traffic${RST}"
echo ""
divider

# ── Argument parsing ──────────────────────────────────────────────────────────
SKIP_SYNTH=false
SKIP_BROWSER=false
REBUILD_FLAG=""

for arg in "$@"; do
  case $arg in
    --skip-synth)   SKIP_SYNTH=true ;;
    --skip-browser) SKIP_BROWSER=true ;;
    --rebuild)      REBUILD_FLAG="--build" ;;
    *) err "Unknown argument: $arg"; exit 1 ;;
  esac
done

# ── Preflight ─────────────────────────────────────────────────────────────────
phase "Preflight"

check_cmd() {
  if command -v "$1" &>/dev/null; then
    ok "$1"
  else
    err "$1 not found — install it first"
    exit 1
  fi
}

check_cmd docker
check_cmd curl

if docker compose version &>/dev/null 2>&1; then
  DC="docker compose"
elif command -v docker-compose &>/dev/null; then
  DC="docker-compose"
else
  err "docker compose not available"
  exit 1
fi
ok "docker compose $($DC version --short 2>/dev/null || echo 'ok')"

if [[ ! -f .env ]]; then
  warn ".env not found — copying .env.example"
  cp .env.example .env
fi
ok ".env present"

# Browser open utility
if command -v open &>/dev/null; then
  OPEN_CMD="open"
elif command -v xdg-open &>/dev/null; then
  OPEN_CMD="xdg-open"
else
  OPEN_CMD=""
  warn "No browser-open utility — URLs will be printed instead"
fi

# y_eet-synth availability
SYNTH_AVAILABLE=false
if [[ "$SKIP_SYNTH" == "false" ]]; then
  if [[ -d "$REPO_ROOT/y_eet-synth/.venv" ]]; then
    SYNTH_AVAILABLE=true
    ok "y_eet-synth venv found"
  elif command -v python3 &>/dev/null; then
    info "y_eet-synth venv not found — running make install..."
    (cd "$REPO_ROOT/y_eet-synth" && make install) || { err "make install failed — synthetic traffic disabled"; SKIP_SYNTH=true; }
    if [[ "$SKIP_SYNTH" == "false" ]]; then
      SYNTH_AVAILABLE=true
      ok "y_eet-synth venv ready"
    fi
  fi
fi

phase_done

# ── Service URLs ──────────────────────────────────────────────────────────────
API_URL="http://localhost:8080"
GRAFANA_URL="http://localhost:3000"
PROMETHEUS_URL="http://localhost:9090"
TEMPO_URL="http://localhost:3200"
LOKI_URL="http://localhost:3100"
ALERTMANAGER_URL="http://localhost:9093"
SENTIMENT_METRICS_URL="http://localhost:9465/metrics"
SENTIMENT_DASHBOARD_URL="http://localhost:8501"

# ── Docker services ───────────────────────────────────────────────────────────
phase "Starting Docker services"

if [[ -n "$REBUILD_FLAG" ]]; then
  info "Rebuilding images (--rebuild)..."
  $DC build --no-cache
fi

info "Bringing up stack (first run pulls images — may take a few minutes)..."
$DC up -d $REBUILD_FLAG 2>&1 | grep -E "Created|Started|Pulling|Building|^#" | sed 's/^/    /' || true

phase_done

# ── Wait: API ─────────────────────────────────────────────────────────────────
phase "Waiting for API"
MAX_WAIT=120
ELAPSED=0
DOTS=0

until curl -sf "$API_URL/health/live" &>/dev/null; do
  if [[ $ELAPSED -ge $MAX_WAIT ]]; then
    err "API did not become healthy within ${MAX_WAIT}s"
    echo ""
    echo -e "  ${YLW}Troubleshooting:${RST}"
    echo -e "    docker compose logs api"
    echo -e "    docker compose ps"
    exit 1
  fi
  DOTS=$(( (DOTS + 1) % 4 ))
  SPIN=("⠋" "⠙" "⠹" "⠸")
  printf "\r  ${DIM}${SPIN[$DOTS]} waiting... ${ELAPSED}s${RST}  "
  sleep 3
  ELAPSED=$(( ELAPSED + 3 ))
done
printf "\r\033[K"
ok "API healthy  →  $API_URL"

phase_done

# ── Database migrations ───────────────────────────────────────────────────────
phase "Database"
$DC exec -T api npm run migrate 2>&1 | tail -3 | sed 's/^/    /' || warn "Migrations may have already run"
ok "Migrations applied"
phase_done

# ── Wait: Grafana ─────────────────────────────────────────────────────────────
phase "Waiting for Grafana"
ELAPSED=0
until curl -sf "$GRAFANA_URL/api/health" &>/dev/null; do
  if [[ $ELAPSED -ge 60 ]]; then
    warn "Grafana not ready after 60s — dashboards may still be loading"
    break
  fi
  DOTS=$(( (DOTS + 1) % 4 ))
  printf "\r  ${DIM}${SPIN[$DOTS]} waiting... ${ELAPSED}s${RST}  "
  sleep 3
  ELAPSED=$(( ELAPSED + 3 ))
done
printf "\r\033[K"
ok "Grafana ready  →  $GRAFANA_URL"
phase_done

# ── Wait: Prometheus ──────────────────────────────────────────────────────────
phase "Waiting for Prometheus"
ELAPSED=0
until curl -sf "$PROMETHEUS_URL/-/ready" &>/dev/null; do
  if [[ $ELAPSED -ge 30 ]]; then
    warn "Prometheus not ready — continuing"
    break
  fi
  sleep 3
  ELAPSED=$(( ELAPSED + 3 ))
done
printf "\r\033[K"
ok "Prometheus ready  →  $PROMETHEUS_URL"
phase_done

# ── Brand Intelligence demo seed ─────────────────────────────────────────────
phase "Seeding Brand Intelligence demo data"
ELAPSED=0
until $DC exec -T social-sentiment python3 -c "import sys; sys.exit(0)" &>/dev/null; do
  if [[ $ELAPSED -ge 60 ]]; then
    warn "social-sentiment container not ready — skipping demo seed"
    break
  fi
  sleep 3
  ELAPSED=$(( ELAPSED + 3 ))
done

if [[ $ELAPSED -lt 60 ]]; then
  $DC exec -T social-sentiment python3 scripts/seed_demo.py \
    && ok "Demo data seeded  →  Brand Intelligence dashboard ready" \
    || warn "Demo seed failed — dashboard will show empty state until pipeline runs"
fi
phase_done

# ── Synthetic traffic ─────────────────────────────────────────────────────────
SYNTH_PID=""

if [[ "$SKIP_SYNTH" == "false" && "$SYNTH_AVAILABLE" == "true" ]]; then
  phase "Synthetic traffic"
  cd "$REPO_ROOT/y_eet-synth"
  SYNTH_BASE_URL="$API_URL" .venv/bin/python main.py run \
    --profile normal \
    --duration 600 \
    --base-url "$API_URL" \
    --json-report /tmp/y_eet-synth-report.json \
    &>/tmp/y_eet-synth.log &
  SYNTH_PID=$!
  cd "$REPO_ROOT"
  ok "y_eet-synth running  (PID $SYNTH_PID)"
  info "Profile: normal · Duration: 10 min · Log: /tmp/y_eet-synth.log"
  phase_done
fi

# ── Open browser tabs ─────────────────────────────────────────────────────────
if [[ "$SKIP_BROWSER" == "false" ]]; then
  open_tab() {
    if [[ -n "$OPEN_CMD" ]]; then
      $OPEN_CMD "$1" 2>/dev/null || true
      sleep 0.4
    fi
  }

  sleep 1
  open_tab "$GRAFANA_URL"
  open_tab "$GRAFANA_URL/d/api-reliability"
  open_tab "$PROMETHEUS_URL"
  if [[ "$SKIP_SYNTH" == "false" && "$SYNTH_AVAILABLE" == "true" ]]; then
    open_tab "$SENTIMENT_DASHBOARD_URL"
  fi

  if [[ -z "$OPEN_CMD" ]]; then
    warn "Open these in your browser:"
    echo "    $GRAFANA_URL"
    echo "    $PROMETHEUS_URL"
    [[ "$SYNTH_AVAILABLE" == "true" ]] && echo "    $SENTIMENT_DASHBOARD_URL"
  fi
fi

# ── Demo ready ────────────────────────────────────────────────────────────────
echo ""
divider
echo ""
echo -e "  ${GRN}${BLD}  DEMO READY${RST}"
echo ""
echo -e "  ${BLD}Core Platform${RST}"
echo -e "    API                    ${CYN}$API_URL${RST}"
echo -e "    API metrics            ${CYN}http://localhost:9464/metrics${RST}"
echo ""
echo -e "  ${BLD}Observability${RST}"
echo -e "    Grafana                ${CYN}$GRAFANA_URL${RST}  ${DIM}(anonymous admin — no login)${RST}"
echo -e "    ├─ API Reliability     ${CYN}$GRAFANA_URL/d/api-reliability${RST}"
echo -e "    ├─ SLO / Error Budget  ${CYN}$GRAFANA_URL/d/slo-error-budget${RST}"
echo -e "    └─ Brand Intel (Exec)  ${CYN}$GRAFANA_URL/d/brand-intel-exec${RST}"
echo -e "    Prometheus             ${CYN}$PROMETHEUS_URL${RST}"
echo -e "    Alertmanager           ${CYN}$ALERTMANAGER_URL${RST}"
echo -e "    Tempo (traces)         ${CYN}$TEMPO_URL${RST}"
echo ""
echo -e "  ${BLD}Brand Intelligence${RST}"
echo -e "    Sentiment metrics      ${CYN}$SENTIMENT_METRICS_URL${RST}"
echo -e "    Streamlit analyst UI   ${CYN}$SENTIMENT_DASHBOARD_URL${RST}"
echo ""

if [[ -n "$SYNTH_PID" ]]; then
  echo -e "  ${BLD}Synthetic traffic${RST}      ${GRN}active${RST}  ${DIM}(PID $SYNTH_PID · log: /tmp/y_eet-synth.log)${RST}"
else
  echo -e "  ${BLD}Synthetic traffic${RST}      ${DIM}not running  (run: cd y_eet-synth && make install)${RST}"
fi

echo ""
echo -e "  ${DIM}What to watch:${RST}"
echo -e "  ${DIM}· Grafana → API Reliability: request rate, error rate, P99 latency${RST}"
echo -e "  ${DIM}· Grafana → SLO Error Budget: burn rate for bet placement + auth${RST}"
echo -e "  ${DIM}· Grafana → Brand Intel: sentiment signals, mention volume, alerts${RST}"
echo -e "  ${DIM}· Prometheus Explore: query social_* and y_eet_* metrics directly${RST}"
echo ""
divider
echo ""

# ── Cleanup trap ──────────────────────────────────────────────────────────────
cleanup() {
  echo ""
  phase "Shutting down"
  [[ -n "$SYNTH_PID" ]] && kill "$SYNTH_PID" 2>/dev/null || true
  info "Docker services left running — stop with: docker compose down"
  [[ -n "$SYNTH_PID" ]] && info "Synth report: /tmp/y_eet-synth-report.json"
  echo ""
}
trap cleanup INT TERM

if [[ -n "$SYNTH_PID" ]]; then
  echo -e "  ${CYN}${BLD}Traffic is flowing.${RST}  ${DIM}Ctrl+C to stop synthetic traffic and exit.${RST}"
  echo ""
  wait "$SYNTH_PID" 2>/dev/null || true
  ok "Synthetic traffic run complete  →  /tmp/y_eet-synth-report.json"
else
  echo -e "  ${CYN}${BLD}Stack is running.${RST}  ${DIM}Ctrl+C to exit (Docker services stay up).${RST}"
  echo ""
  wait
fi
